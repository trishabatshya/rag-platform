"""Bounded extraction, endpoint salvage, outage aborts and success-only disk cache."""

import hashlib
import json
import logging
import os
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import get_args
from uuid import uuid4

from pydantic import ValidationError

from app.config import ROOT, Settings, compute_cost
from app.llm import complete
from graphrag.dataset import Paragraph
from graphrag.extraction_provenance import load_first_fill, save_first_fill, summarize_first_fill
from graphrag.schema import Entity, EntityType, Extraction, RelationType

logger = logging.getLogger(__name__)

ENTITY_ALIASES = {
    **dict.fromkeys(("COUNTY", "CITY", "STATE", "COUNTRY", "REGION", "PROVINCE"), "PLACE"),
    **dict.fromkeys(("MOVIE", "SONG", "ALBUM", "DVD", "SINGLE", "PLAY"), "WORK"),
    **dict.fromkeys(("BAND", "COMPANY", "ORGANIZATION"), "ORG"),
    "OPERATION": "EVENT",
}


def repair_extraction(payload: dict) -> tuple[Extraction, dict, bool]:
    """Repair known shape/type drift without expanding the fixed schema vocabulary."""
    original = deepcopy(payload)
    counts = dict(
        repaired_entity_types=0,
        repaired_relation_types=0,
        dropped_relations=0,
        coerced_string_entities=0,
        dropped_entities=0,
    )

    def entity(value):
        if isinstance(value, str):
            counts["coerced_string_entities"] += 1
            value = {"name": value, "type": "OTHER"}
        if not isinstance(value, dict):
            raise ValueError("Entity must be an object or string")
        if isinstance(value.get("name"), str) and not value["name"].strip():
            return None
        kind = value.get("type")
        if kind not in get_args(EntityType):
            value["type"] = ENTITY_ALIASES.get(str(kind).upper(), "OTHER")
            counts["repaired_entity_types"] += 1
        return value

    if not isinstance(payload, dict):
        raise ValueError("Extraction must be an object")
    if not all(isinstance(payload.get(name), list) for name in ("entities", "relations")):
        raise ValueError("entities and relations must be arrays")
    entities = []
    for value in payload.get("entities", []):
        repaired = entity(value)
        if repaired is None:
            counts["dropped_entities"] += 1
        else:
            entities.append(repaired)
    payload["entities"] = entities
    known = {Entity.model_validate(e) for e in entities}
    relations = []
    for relation in payload.get("relations", []):
        if not isinstance(relation, dict):
            raise ValueError("Relation must be an object")
        if relation.get("type") not in get_args(RelationType):
            relation["type"] = "RELATED_TO"
            counts["repaired_relation_types"] += 1
        for endpoint in ("source", "target"):
            value = relation.get(endpoint)
            if isinstance(value, str):
                matches = [e for e in entities if e["name"] == value]
                value = dict(matches[0]) if len(matches) == 1 else value
            relation[endpoint] = entity(value)
        if any(
            relation[e] is None or Entity.model_validate(relation[e]) not in known
            for e in ("source", "target")
        ):
            counts["dropped_relations"] += 1
        else:
            relations.append(relation)
    payload["relations"] = relations
    return Extraction.model_validate(payload), counts, payload != original


@dataclass
class IndexingUsage:
    """New extraction usage, excluding persisted cache hits; time is wall-clock measured."""

    in_tokens: int = 0
    out_tokens: int = 0
    reference_cost: float = 0.0
    elapsed_ms: float = 0.0
    cache_hits: int = 0
    skipped_chunks: int = 0
    calls: int = 0
    kept_relations: int = 0
    dropped_relations: int = 0
    failed_chunks: int = 0
    skipped_chunk_details: list[dict] = field(default_factory=list)
    skipped_reasons: dict[str, int] = field(default_factory=dict)
    chunks_attempted: int = 0
    extracted_cleanly: int = 0
    extracted_after_repair: int = 0
    repaired_entity_types: int = 0
    repaired_relation_types: int = 0
    coerced_string_entities: int = 0
    dropped_entities: int = 0


class Extractor:
    """Reuse strict extractions keyed by text, model, mode, schema and mock annotation."""

    def __init__(
        self,
        cache_dir: Path | None = None,
        model: str | None = None,
        failure_log: Path | None = None,
        fresh_extraction: bool = False,
    ) -> None:
        self.settings = Settings()
        self.model = model or self.settings.extract_model
        self.cache_dir = cache_dir or Path(
            os.getenv(
                "GRAPH_EXTRACT_CACHE",
                str(ROOT / "data" / "runtime" / "graph_extract"),
            )
        )
        self.usage = IndexingUsage()
        self.fresh_extraction = fresh_extraction
        self.first_fills: dict[str, dict | None] = {}
        self.timeout = float(os.getenv("EXTRACT_TIMEOUT_SECONDS", "90"))
        if not 0 < self.timeout < float("inf"):
            raise ValueError("EXTRACT_TIMEOUT_SECONDS must be positive and finite")
        self.consecutive_timeouts = 0
        self.max_tokens = int(os.getenv("EXTRACT_MAX_TOKENS", "1000"))
        if self.max_tokens <= 0:
            raise ValueError("EXTRACT_MAX_TOKENS must be a positive integer")
        self.failure_log = failure_log or Path(
            os.getenv(
                "EXTRACT_FAILURE_LOG", str(ROOT / "eval" / "results" / "extraction_failures.log")
            )
        )

    def failure_detail(self, chunk: Paragraph, attempt: int, error: str, text: str = "") -> None:
        """Append full diagnostics to disk, keeping provider/schema dumps off the console."""
        self.failure_log.parent.mkdir(parents=True, exist_ok=True)
        with self.failure_log.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "mode": self.settings.mode.upper(),
                        "chunk_id": chunk.id,
                        "attempt": attempt,
                        "error": error,
                        "raw": text,
                    }
                )
                + "\n"
            )

    def record_skip(self, chunk: Paragraph, reason: str, attempts: int) -> None:
        """Record one fully skipped chunk without persisting a failed extraction."""
        self.usage.skipped_chunks += 1
        self.usage.failed_chunks += 1
        logger.warning("Skipping %s: %s", chunk.id, reason)
        self.usage.skipped_reasons[reason] = self.usage.skipped_reasons.get(reason, 0) + 1
        self.usage.skipped_chunk_details.append(
            {"chunk_id": chunk.id, "reason": reason, "attempts": attempts}
        )

    def write_skipped(self, path: Path) -> None:
        """Write a mode-labeled JSON-lines diagnostic, including on aborted indexing."""
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = ["MOCK (not a result)" if self.settings.mode == "mock" else "REAL"]
        lines.extend(
            json.dumps(row, ensure_ascii=False) for row in self.usage.skipped_chunk_details
        )
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def extract(self, chunk: Paragraph) -> Extraction | None:
        """Skip a chunk after validation/provider failure; corrupt cache entries are rebuilt."""
        start = perf_counter()
        try:
            return self._extract(chunk)
        finally:
            self.usage.elapsed_ms += (perf_counter() - start) * 1000

    def _extract(self, chunk: Paragraph) -> Extraction | None:
        fill_start = perf_counter()
        before = {
            key: getattr(self.usage, key)
            for key in ("in_tokens", "out_tokens", "reference_cost", "calls")
        }
        annotation = chunk.annotation.model_dump_json() if chunk.annotation else ""
        material = json.dumps(
            [
                "schema-v1",
                self.settings.mode,
                self.model,
                chunk.text,
                annotation if self.settings.mode == "mock" else "",
            ]
        )
        key = hashlib.sha256(material.encode()).hexdigest()
        path = self.cache_dir / f"{key}.json"
        metadata_path = self.cache_dir / "provenance" / f"{key}.json"
        existing = path.exists()
        first_fill = load_first_fill(metadata_path)
        if existing:
            self.first_fills[key] = first_fill
        if existing and not self.fresh_extraction:
            try:
                result = Extraction.model_validate_json(path.read_text(encoding="utf-8"))
                self.usage.cache_hits += 1
                self.usage.kept_relations += len(result.relations)
                return result
            except (ValidationError, ValueError):
                logger.warning("Invalid extraction cache %s; rebuilding", path)
        self.usage.chunks_attempted += 1
        schema = Extraction.model_json_schema()
        for name in ("entities", "relations"):
            schema["properties"][name]["maxItems"] = 8
        prompt = (
            "Extract only the most important explicit facts: at most 8 entities and 8 relations. "
            "Use declared typed entities as relation endpoints. Return compact JSON.\n" + chunk.text
        )
        reason = "validation failure"
        for attempt in range(3):
            text = ""
            try:
                if self.settings.mode == "mock":
                    if chunk.annotation is None:
                        raise ValueError("Mock extraction requires fixture annotations")
                    # Annotations simulate perfect extraction, not real inference or paid usage.
                    text = annotation
                else:
                    try:
                        response = complete(
                            prompt,
                            self.model,
                            system="GRAPH_EXTRACT",
                            json_mode=True,
                            timeout=self.timeout,
                            max_tokens=self.max_tokens,
                            response_format={
                                "type": "json_schema",
                                "json_schema": {
                                    "name": "Extraction",
                                    "strict": True,
                                    "schema": schema,
                                },
                            },
                        )
                    except Exception as exc:
                        chain = exc
                        unavailable = False
                        while chain is not None:
                            unavailable |= isinstance(
                                chain, (TimeoutError, ConnectionError)
                            ) or any(
                                word in (type(chain).__name__ + " " + str(chain)).lower()
                                for word in ("timeout", "timed out", "connection", "unreachable")
                            )
                            chain = chain.__cause__ or chain.__context__
                        self.consecutive_timeouts = (
                            self.consecutive_timeouts + 1 if unavailable else 0
                        )
                        reason = "timeout" if unavailable else "provider failure"
                        if self.consecutive_timeouts >= 3:
                            self.failure_detail(chunk, attempt + 1, str(exc))
                            self.record_skip(chunk, reason, attempt + 1)
                            raise ExtractionUnavailable(
                                "Graph extraction aborted after 3 consecutive timeout/connection "
                                f"failures ({self.timeout:g}s per call). Check Ollama and "
                                "OLLAMA_API_BASE, then rerun; failed chunks are not cached."
                            ) from exc
                        # Provider exception classes vary; normalize only the completion boundary.
                        raise RuntimeError(f"Completion failed: {exc}") from exc
                    self.consecutive_timeouts = 0
                    self.usage.calls += 1
                    self.usage.in_tokens += response.in_tokens
                    self.usage.out_tokens += response.out_tokens
                    self.usage.reference_cost += compute_cost(
                        response.model,
                        response.in_tokens,
                        response.out_tokens,
                    )
                    text = response.text
                    if response.finish_reason in {"length", "max_tokens"}:
                        self.failure_detail(chunk, attempt + 1, "Token limit reached", text)
                        self.record_skip(chunk, "truncated JSON", attempt + 1)
                        return None
                reason = "validation failure"
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError as exc:
                    if exc.pos >= len(text.rstrip()) or "Unterminated" in exc.msg:
                        self.failure_detail(chunk, attempt + 1, str(exc), text)
                        self.record_skip(chunk, "truncated JSON", attempt + 1)
                        return None
                    raise
                result, counts, repaired = repair_extraction(payload)
                self.usage.extracted_after_repair += int(repaired)
                self.usage.extracted_cleanly += int(not repaired)
                for name, count in counts.items():
                    setattr(self.usage, name, getattr(self.usage, name) + count)
                self.usage.kept_relations += len(result.relations)
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                temporary = path.with_suffix(f".{uuid4().hex}.tmp")
                temporary.write_text(result.model_dump_json(), encoding="utf-8")
                temporary.replace(path)
                if not existing:
                    first_fill = {
                        "status": "measured",
                        "mode": self.settings.mode.upper(),
                        "model": self.model,
                        "cache_key": key,
                        "filled_at": datetime.now(UTC).isoformat(),
                        "elapsed_ms": (perf_counter() - fill_start) * 1000,
                        **{
                            name: getattr(self.usage, name) - value
                            for name, value in before.items()
                        },
                    }
                    # Never replace a known original fill with a later regeneration's costs.
                    if not metadata_path.exists():
                        save_first_fill(metadata_path, first_fill)
                    self.first_fills[key] = load_first_fill(metadata_path)
                return result
            except (ValueError, RuntimeError, ConnectionError) as exc:
                self.failure_detail(chunk, attempt + 1, str(exc), text)
        self.record_skip(chunk, reason, 3)
        return None

    def first_fill_summary(self) -> dict:
        """Expose original cache-fill time/tokens separately from this run's actual usage."""
        return summarize_first_fill(list(self.first_fills.values()))


class ExtractionUnavailable(Exception):
    """Abort indexing after three consecutive unavailable extraction calls."""

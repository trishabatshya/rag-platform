"""Validated extraction with four attempts (initial plus three retries) and disk cache."""

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from pydantic import ValidationError

from app.config import ROOT, Settings, compute_cost
from app.llm import complete
from graphrag.dataset import Paragraph
from graphrag.schema import Extraction

logger = logging.getLogger(__name__)


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


class Extractor:
    """Reuse strict extractions keyed by text, model, mode, schema and mock annotation."""

    def __init__(self, cache_dir: Path | None = None, model: str | None = None) -> None:
        self.settings = Settings()
        self.model = model or self.settings.extract_model
        self.cache_dir = cache_dir or Path(
            os.getenv(
                "GRAPH_EXTRACT_CACHE",
                str(ROOT / "data" / "runtime" / "graph_extract"),
            )
        )
        self.usage = IndexingUsage()

    def extract(self, chunk: Paragraph) -> Extraction | None:
        """Skip a chunk after validation/provider failure; corrupt cache entries are rebuilt."""
        start = perf_counter()
        try:
            return self._extract(chunk)
        finally:
            self.usage.elapsed_ms += (perf_counter() - start) * 1000

    def _extract(self, chunk: Paragraph) -> Extraction | None:
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
        if path.exists():
            try:
                result = Extraction.model_validate_json(path.read_text(encoding="utf-8"))
                self.usage.cache_hits += 1
                return result
            except (ValidationError, ValueError):
                logger.warning("Invalid extraction cache %s; rebuilding", path)
        schema = json.dumps(Extraction.model_json_schema())
        prompt = f"Extract only explicit facts. JSON schema: {schema}\nParagraph:\n{chunk.text}"
        for attempt in range(4):
            try:
                if self.settings.mode == "mock":
                    if chunk.annotation is None:
                        raise ValueError("Mock extraction requires fixture annotations")
                    # Annotations simulate perfect extraction, not real inference or paid usage.
                    text = annotation
                else:
                    try:
                        response = complete(
                            prompt, self.model, system="GRAPH_EXTRACT", json_mode=True
                        )
                    except Exception as exc:
                        # Provider exception classes vary; normalize only the completion boundary.
                        raise RuntimeError(f"Completion failed: {exc}") from exc
                    self.usage.calls += 1
                    self.usage.in_tokens += response.in_tokens
                    self.usage.out_tokens += response.out_tokens
                    self.usage.reference_cost += compute_cost(
                        response.model,
                        response.in_tokens,
                        response.out_tokens,
                    )
                    text = response.text
                result = Extraction.model_validate_json(text)
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                temporary = path.with_suffix(f".{uuid4().hex}.tmp")
                temporary.write_text(result.model_dump_json(), encoding="utf-8")
                temporary.replace(path)
                return result
            except (ValueError, RuntimeError, ConnectionError) as exc:
                logger.warning("Extraction %s attempt %s failed: %s", chunk.id, attempt + 1, exc)
                prompt += (
                    "\nPrevious output failed. Return strictly valid JSON matching the schema."
                )
        self.usage.skipped_chunks += 1
        logger.error("Skipping graph extraction for chunk %s after three retries", chunk.id)
        return None

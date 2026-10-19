"""Durable per-question GraphRAG checkpoints scoped to corpus and generation settings."""

import hashlib
import json
import logging
import os
from dataclasses import asdict
from pathlib import Path

from app.config import Settings
from graphrag.dataset import Corpus


def checkpoint_path(
    directory: Path,
    corpus: Corpus,
    embedding_resolution: bool,
    graph_fingerprint: str | None = None,
) -> Path:
    """Isolate checkpoints by data, mode, models, limits, endpoint and resolution policy."""
    settings = Settings()
    context = {
        "version": 2,
        "resolver": "ratio92-person-first-last-subset",
        "graph_fingerprint": graph_fingerprint,
        "corpus": asdict(corpus),
        "mode": settings.mode,
        "model": settings.large_model,
        "extract_model": settings.extract_model,
        "embedding_model": settings.embedding_model,
        "ollama": settings.ollama_api_base,
        "embedding_resolution": embedding_resolution,
        "limits": {
            name: os.getenv(name, default)
            for name, default in (
                ("LLM_TIMEOUT_SECONDS", "120"),
                ("LLM_MAX_TOKENS", "400"),
                ("EXTRACT_TIMEOUT_SECONDS", "90"),
                ("EXTRACT_MAX_TOKENS", "1000"),
            )
        },
    }
    key = hashlib.sha256(
        json.dumps(context, sort_keys=True, default=lambda obj: obj.model_dump()).encode()
    ).hexdigest()
    return directory / f"graph_checkpoint_{key}.jsonl"


def load_checkpoint(path: Path) -> dict[tuple[str, str], dict]:
    """Read terminal results; recover only an incomplete trailing write after interruption."""
    if not path.exists():
        return {}
    lines = path.read_bytes().splitlines(keepends=True)
    rows, offset = {}, 0
    for index, line in enumerate(lines):
        try:
            row = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            if index != len(lines) - 1:
                raise ValueError(f"Corrupt checkpoint at line {index + 1}: {path}") from None
            with path.open("r+b") as handle:
                handle.truncate(offset)
            logging.warning("Discarded interrupted trailing checkpoint write: %s", path.name)
            break
        if row.get("status") not in {"completed", "failed"}:
            raise ValueError(f"Invalid checkpoint status: {path}")
        key = row["system"], row["question_id"]
        if key in rows:
            raise ValueError(f"Duplicate checkpoint question: {key}")
        rows[key] = row
        offset += len(line)
    return rows


def append_checkpoint(path: Path, row: dict) -> None:
    """Flush and fsync each terminal question before starting the next request."""
    with path.open("a+b") as handle:
        if handle.tell():
            handle.seek(-1, 2)
            if handle.read(1) != b"\n":
                handle.write(b"\n")
        handle.write((json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8"))
        handle.flush()
        os.fsync(handle.fileno())

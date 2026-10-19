"""Persistent first-fill extraction measurements, separate from current cache-hit costs."""

import json
import math
from pathlib import Path
from uuid import uuid4

METRICS = ("elapsed_ms", "in_tokens", "out_tokens", "reference_cost", "calls")


def load_first_fill(path: Path) -> dict | None:
    """Treat absent or invalid historical measurements as unknown, never as zero."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("status") != "measured" or not all(
            isinstance(data.get(key), (int, float)) and math.isfinite(data[key]) and data[key] >= 0
            for key in METRICS
        ):
            return None
        return data
    except (ValueError, TypeError, AttributeError):
        return None


def save_first_fill(path: Path, data: dict) -> None:
    """Persist provenance alongside successful cache entries using an atomic replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{uuid4().hex}.tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def summarize_first_fill(records: list[dict | None]) -> dict:
    """Sum first-fill measurements; expose null totals if any legacy history is missing."""
    known = [record for record in records if record is not None]
    partial = {key: sum(record[key] for record in known) for key in METRICS}
    return {
        "status": "no_fills"
        if not records
        else "measured"
        if len(known) == len(records)
        else "unknown"
        if not known
        else "partial",
        "known_chunks": len(known),
        "unknown_chunks": len(records) - len(known),
        **{key: value if len(known) == len(records) else None for key, value in partial.items()},
        "known_totals": partial,
        "scope": "First successful cache fills, including same-fill retries; excludes failed "
        "uncached runs, embeddings, reranking, storage and compute charges. "
        "Legacy first-fill measurements cannot be reconstructed from cache hits. "
        "Token/reference-cost totals cover completed provider replies; usage of timed-out "
        "provider calls is unknown.",
    }

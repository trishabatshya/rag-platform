"""Evaluate baseline RAG and write provenance-rich, mode-labeled CSV results."""

import argparse
import csv
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Self

import numpy as np
from pydantic import BaseModel, Field, model_validator

from app.config import ROOT, Settings, compute_cost
from app.corpus_state import CorpusState
from app.rag import RAGEngine, close_engine, get_engine
from eval.judge import judge, reference_in_answer


class EvalItem(BaseModel):
    """Reviewed reference item; unknown questions have no expected source."""

    id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    reference: str = Field(min_length=1)
    source: str | None
    answerable: bool
    needs_review: bool = False

    @model_validator(mode="after")
    def validate_reference(self) -> Self:
        """Require a source for answerable items and abstention for unanswerable items."""
        if self.answerable and not self.source:
            raise ValueError("Answerable items require an expected source")
        if not self.answerable and (self.source is not None or self.reference != "I don't know"):
            raise ValueError("Unanswerable items require null source and I don't know reference")
        if self.needs_review:
            raise ValueError("Candidate items must be human-reviewed before evaluation")
        return self


def load_items(path: Path, limit: int | None = None) -> list[EvalItem]:
    """Read UTF-8 JSONL, validating every item and unique IDs before evaluation."""
    if limit is not None and limit <= 0:
        raise ValueError("limit must be positive")
    items = [
        EvalItem.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not items:
        raise ValueError("Evaluation dataset must not be empty")
    if len({item.id for item in items}) != len(items):
        raise ValueError("Evaluation item IDs must be unique")
    return items[:limit] if limit else items


def summarize(rows: list[dict]) -> dict[str, float | int | None]:
    """Summarize measured rows; hit rate excludes questions without an expected source."""
    hits = [float(row["hit"]) for row in rows if row["hit"] != ""]
    latencies = [row["latency_ms"] for row in rows]
    parsed = [row for row in rows if row["correct"] is not None]
    references = [r for r in rows if r.get("reference_in_answer") is not None]
    paired = [r for r in parsed if r.get("reference_in_answer") is not None]
    disagreements = sum(r["correct"] != r["reference_in_answer"] for r in paired)
    accuracy = float(np.mean([r["correct"] for r in parsed])) if parsed else None
    return {
        "count": len(rows),
        "correctness": accuracy,
        "judge_accuracy": accuracy,
        "judge_parsed_count": len(parsed),
        "judge_unparseable_count": len(rows) - len(parsed),
        "reference_in_answer_accuracy": float(
            np.mean([r["reference_in_answer"] for r in references])
        )
        if references
        else None,
        "disagreement_count": disagreements,
        "disagreement_rate": disagreements / len(paired) if paired else None,
        "disagreement_compared_count": len(paired),
        "hit_rate": float(np.mean(hits)) if hits else None,
        "p50_latency_ms": float(np.percentile(latencies, 50)),
        "p95_latency_ms": float(np.percentile(latencies, 95)),
        "mean_reference_cost_usd": float(np.mean([row["cost"] for row in rows])),
    }


def run_evaluation(
    dataset: Path,
    output_dir: Path,
    tag: str,
    limit: int | None = None,
    engine: RAGEngine | None = None,
) -> tuple[Path, dict]:
    """Evaluate reviewed items and atomically publish a complete timestamped CSV."""
    if not re.fullmatch(r"[A-Za-z0-9_-]+", tag):
        raise ValueError("Tag must contain only letters, digits, underscores or hyphens")
    items = load_items(dataset, limit)
    settings = Settings()
    engine = engine or get_engine()
    version = CorpusState(settings.state_db).version
    # Discard the first retrieval/generation so embedding/model initialization is untimed.
    # Warm the judge separately too; its model may differ from the answering model.
    warmup = engine.answer("Warm-up: reply briefly with READY.", settings.large_model)
    warmup_judge = judge("What is the ready signal?", "READY", "READY")
    rows = []
    for item in items:
        response = engine.answer(item.question, settings.large_model)
        verdict = judge(item.question, response["answer"], item.reference)
        retrieved = list(dict.fromkeys(chunk["source"] for chunk in response["chunks"]))
        rows.append(
            {
                "id": item.id,
                "question": item.question,
                "reference": item.reference,
                "expected_source": item.source or "",
                "answerable": int(item.answerable),
                "answer": response["answer"],
                "retrieved_sources": json.dumps(retrieved),
                "cited_sources": json.dumps(response["sources"]),
                "chunk_ids": json.dumps([chunk["id"] for chunk in response["chunks"]]),
                "hit": int(item.source in retrieved) if item.answerable else "",
                "correct": int(verdict.correct) if verdict.correct is not None else None,
                "reference_in_answer": int(reference_in_answer(response["answer"], item.reference)),
                "f1": verdict.f1,
                "judge_method": verdict.method,
                "judge_raw": verdict.raw,
                "judge_label": verdict.label,
                "latency_scope": "warmed answer pipeline; excludes warm-up and judging",
                "latency_ms": response["latency_ms"],
                "in_tokens": response["in_tokens"],
                "out_tokens": response["out_tokens"],
                "model": response["model"],
                "cost": compute_cost(
                    response["model"], response["in_tokens"], response["out_tokens"]
                ),
                "judge_in_tokens": verdict.in_tokens,
                "judge_out_tokens": verdict.out_tokens,
                "judge_cost": verdict.cost,
                "mode": settings.mode.upper(),
                "run_tag": tag,
                "cost_basis": "estimated at reference prices",
                "corpus_version": version,
            }
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    path = output_dir / f"{tag}_{timestamp}.csv"
    temporary = path.with_suffix(".csv.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    summary = summarize(rows)
    summary.update(
        {
            "warmup_calls": 1 + int(warmup_judge.method == "llm"),
            "warmup_in_tokens": warmup["in_tokens"] + warmup_judge.in_tokens,
            "warmup_out_tokens": warmup["out_tokens"] + warmup_judge.out_tokens,
            "warmup_reference_cost_usd": compute_cost(
                warmup["model"], warmup["in_tokens"], warmup["out_tokens"]
            )
            + warmup_judge.cost,
        }
    )
    return path, summary


def main() -> None:
    """Run baseline evaluation and print metrics that came from this run only."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", default="baseline")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--dataset", type=Path, default=ROOT / "data" / "eval.jsonl")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "eval" / "results")
    args = parser.parse_args()
    try:
        path, summary = run_evaluation(args.dataset, args.output_dir, args.tag, args.limit)
    finally:
        close_engine()
    print(f"{Settings().mode.upper()} - cost estimated at reference prices")
    if Settings().mode == "mock":
        print(
            "MOCK (not a result): fake embeddings/answers/token counts; "
            "measured software timings only."
        )
    print(json.dumps(summary, indent=2))
    print(f"CSV: {path}")


if __name__ == "__main__":
    main()

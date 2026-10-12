"""Three-system GraphRAG evaluation with separate indexing and honest data/mode provenance."""

import argparse
import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean

from app.config import ROOT, Settings, compute_cost
from graphrag.dataset import load_dataset_corpus
from graphrag.decompose import answer_decomposed
from graphrag.index import build_index
from graphrag.metrics import exact_match, f1, supporting_recall
from scripts.failure_analysis import write_failures


def _aggregate(rows: list[dict]) -> dict:
    if not rows:
        return {
            "count": 0,
            "em": None,
            "f1": None,
            "supporting_recall": None,
            "latency_ms": None,
            "in_tokens": None,
            "out_tokens": None,
            "reference_cost": None,
        }
    return {
        "count": len(rows),
        **{
            key: mean(r[key] for r in rows)
            for key in (
                "em",
                "f1",
                "supporting_recall",
                "latency_ms",
                "in_tokens",
                "out_tokens",
                "reference_cost",
            )
        },
    }


def run_benchmark(
    output_dir: Path,
    source: str = "fixture",
    n: int = 150,
    seed: int = 42,
    cache_dir: Path | None = None,
    fallback: bool = True,
    embedding_resolution: bool = False,
) -> tuple[Path, dict]:
    """Replay identical questions, write CSV/summary/review files, and release the graph."""
    settings = Settings()
    if settings.mode == "mock" and source != "fixture":
        raise ValueError("Mock graph extraction requires --dataset fixture")
    corpus = load_dataset_corpus(source, n=n, seed=seed, fallback=fallback)
    output_dir.mkdir(parents=True, exist_ok=True)
    pipeline, indexing = build_index(
        corpus,
        cache_dir=cache_dir,
        report_path=output_dir / "merge_groups.txt",
        embedding_resolution=embedding_resolution,
    )
    label = "MOCK (not a result)" if settings.mode == "mock" else "REAL"
    rows = []
    try:
        for system in ("vector", "graph_hybrid", "decomposition"):
            for question in corpus.questions:
                result = (
                    answer_decomposed(question.question, pipeline)
                    if system == "decomposition"
                    else pipeline.answer(question.question, system=system)
                )
                rows.append(
                    {
                        "mode": label,
                        "dataset": corpus.origin,
                        "system": system,
                        "question_id": question.id,
                        "kind": question.kind,
                        "question": question.question,
                        "gold": question.answer,
                        "predicted": result["answer"],
                        "gold_titles": json.dumps(question.supporting_titles),
                        "retrieved_titles": json.dumps(result["sources"]),
                        "em": exact_match(result["answer"], question.answer),
                        "f1": f1(result["answer"], question.answer),
                        "supporting_recall": supporting_recall(
                            result["sources"], question.supporting_titles
                        ),
                        "latency_ms": result["latency_ms"],
                        "in_tokens": result["in_tokens"],
                        "out_tokens": result["out_tokens"],
                        "reference_cost": compute_cost(
                            result["model"], result["in_tokens"], result["out_tokens"]
                        ),
                    }
                )
    finally:
        pipeline.store.close()
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    csv_path = output_dir / f"project3_{timestamp}.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        "mode": settings.mode.upper(),
        "label": label,
        "dataset": corpus.origin,
        "requested_dataset": source,
        "fallback_reason": corpus.fallback_reason,
        "requested_n": n,
        "question_count": len(corpus.questions),
        "seed": seed,
        "csv": csv_path.name,
        "indexing": indexing,
        "singlehop_definition": "fixture's authored labels; HotpotQA <=1 unique supporting title",
        "token_scope": "generation plus decomposition planner; mock tokens are simulated",
        "latency_scope": (
            "end-to-end query including embedding/retrieval/reranking/planning/generation"
        ),
        "generation_model": settings.large_model,
        "extract_model": settings.extract_model,
        "embedding_model": "hash384" if settings.mode == "mock" else settings.embedding_model,
        "reranker": "lexical_overlap"
        if settings.mode == "mock"
        else "cross-encoder/ms-marco-MiniLM-L-6-v2",
        "systems": {
            system: {
                subset: _aggregate(
                    [
                        r
                        for r in rows
                        if r["system"] == system and (subset == "all" or r["kind"] == subset)
                    ]
                )
                for subset in ("all", "multihop", "singlehop")
            }
            for system in ("vector", "graph_hybrid", "decomposition")
        },
    }
    (output_dir / "summary_project3.json").write_text(
        json.dumps(summary, indent=2) + "\n",
        encoding="utf-8",
    )
    write_failures(csv_path, output_dir / "failure_analysis_project3.md")
    return csv_path, summary


def main() -> None:
    """Expose an offline default and explicit HotpotQA/strict-download controls."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=("fixture", "hotpotqa"), default="fixture")
    parser.add_argument("--n", type=int, default=150)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "eval" / "results")
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--no-fallback", action="store_true")
    parser.add_argument("--embedding-resolution", action="store_true")
    args = parser.parse_args()
    path, summary = run_benchmark(
        args.output_dir,
        source=args.dataset,
        n=args.n,
        seed=args.seed,
        cache_dir=args.cache_dir,
        fallback=not args.no_fallback,
        embedding_resolution=args.embedding_resolution,
    )
    print(f"{summary['label']} | {summary['dataset']} | {summary['question_count']} questions")
    if summary["fallback_reason"]:
        print(f"Fallback: {summary['fallback_reason']}")
    print(path)
    print(args.output_dir / "summary_project3.json")


if __name__ == "__main__":
    main()

"""Three-system GraphRAG evaluation with separate indexing and honest data/mode provenance."""

import argparse
import csv
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from time import perf_counter

from app.config import ROOT, Settings, compute_cost
from eval.graph_checkpoint import append_checkpoint, checkpoint_path, load_checkpoint
from graphrag.dataset import load_dataset_corpus
from graphrag.decompose import answer_decomposed
from graphrag.extract import ExtractionUnavailable
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
            key: mean(r[key] for r in rows if r[key] is not None)
            if any(r[key] is not None for r in rows)
            else None
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
    systems: tuple[str, ...] = ("vector", "graph_hybrid"),
    fresh_extraction: bool = False,
) -> tuple[Path, dict]:
    """Replay identical questions, write CSV/summary/review files, and release the graph."""
    settings = Settings()
    if (
        not systems
        or len(set(systems)) != len(systems)
        or not set(systems) <= {"vector", "graph_hybrid", "decomposition"}
    ):
        raise ValueError("systems must uniquely select vector,graph_hybrid,decomposition")
    if settings.mode == "mock" and source != "fixture":
        raise ValueError("Mock graph extraction requires --dataset fixture")
    corpus = load_dataset_corpus(source, n=n, seed=seed, fallback=fallback)
    output_dir.mkdir(parents=True, exist_ok=True)
    resumed = 0
    try:
        pipeline, indexing = build_index(
            corpus,
            cache_dir=cache_dir,
            report_path=output_dir / "merge_groups.txt",
            embedding_resolution=embedding_resolution,
            fresh_extraction=fresh_extraction,
        )
    except ExtractionUnavailable as exc:
        aborted = {
            "mode": settings.mode.upper(),
            "completed": False,
            "label": "MOCK (not a result)" if settings.mode == "mock" else "REAL",
            "dataset": corpus.origin,
            "error": str(exc),
            "indexing": exc.indexing,
        }
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        for name in ("summary_project3.json", f"project3_aborted_{stamp}.json"):
            (output_dir / name).write_text(json.dumps(aborted, indent=2) + "\n", encoding="utf-8")
        raise
    label = "MOCK (not a result)" if settings.mode == "mock" else "REAL"
    checkpoint = checkpoint_path(
        output_dir, corpus, embedding_resolution, indexing["graph_fingerprint"]
    )
    try:
        finished = load_checkpoint(checkpoint)
    except Exception:
        pipeline.store.close()
        raise
    rows = []
    try:
        for system in systems:
            for question in corpus.questions:
                key = system, question.id
                if key in finished:
                    rows.append(finished[key])
                    resumed += 1
                    continue
                diagnostics = {}
                start = perf_counter()
                row = {
                    "mode": label,
                    "dataset": corpus.origin,
                    "system": system,
                    "question_id": question.id,
                    "kind": question.kind,
                    "question": question.question,
                    "gold": question.answer,
                    "gold_titles": json.dumps(question.supporting_titles),
                    "status": "completed",
                    "failure_reason": "",
                    "timed_out": False,
                    "invalid_decomposition": False,
                }
                try:
                    result = (
                        answer_decomposed(question.question, pipeline, diagnostics=diagnostics)
                        if system == "decomposition"
                        else pipeline.answer(question.question, system=system)
                    )
                    row.update(
                        {
                            "predicted": result["answer"],
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
                except Exception as exc:
                    chain, timed_out = exc, False
                    seen = set()
                    while chain is not None and id(chain) not in seen:
                        seen.add(id(chain))
                        timed_out |= isinstance(chain, TimeoutError) or any(
                            word in (type(chain).__name__ + " " + str(chain)).lower()
                            for word in ("timeout", "timed out")
                        )
                        chain = chain.__cause__ or chain.__context__
                    row.update(
                        {
                            "status": "failed",
                            "failure_reason": f"{type(exc).__name__}: {exc}",
                            "timed_out": timed_out,
                            "predicted": "",
                            "retrieved_titles": "[]",
                            "em": 0.0,
                            "f1": 0.0,
                            "supporting_recall": 0.0,
                            "latency_ms": (perf_counter() - start) * 1000,
                            "in_tokens": None,
                            "out_tokens": None,
                            "reference_cost": None,
                        }
                    )
                    logging.warning("%s %s failed: %s", system, question.id, type(exc).__name__)
                row["invalid_decomposition"] = diagnostics.get("invalid_decomposition", False)
                append_checkpoint(checkpoint, row)
                finished[key] = row
                rows.append(row)
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
        "checkpoint": checkpoint.name,
        "resumed_results": resumed,
        "new_results": len(rows) - resumed,
        "selected_systems": list(systems),
        "failure_metrics": (
            "Failures score zero quality; partial token/cost usage is unknown (null). "
            "Usage averages include known rows only. timed_out is a subset of failed."
        ),
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
                "completed": sum(r["status"] == "completed" for r in rows if r["system"] == system),
                "failed": sum(r["status"] == "failed" for r in rows if r["system"] == system),
                "timed_out": sum(r["timed_out"] for r in rows if r["system"] == system),
                "invalid_decomposition": sum(
                    r["invalid_decomposition"] for r in rows if r["system"] == system
                ),
                **{
                    subset: _aggregate(
                        [
                            r
                            for r in rows
                            if r["system"] == system and (subset == "all" or r["kind"] == subset)
                        ]
                    )
                    for subset in ("all", "multihop", "singlehop")
                },
            }
            for system in systems
        },
    }
    (output_dir / "summary_project3.json").write_text(
        json.dumps(summary, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / f"project3_{timestamp}.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
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
    parser.add_argument(
        "--fresh-extraction",
        action="store_true",
        help="Ignore extraction cache reads to measure fresh extraction usage/time",
    )
    parser.add_argument(
        "--systems",
        default="vector,graph_hybrid",
        help="Comma-separated systems; decomposition runs only when explicitly listed",
    )
    args = parser.parse_args()
    path, summary = run_benchmark(
        args.output_dir,
        source=args.dataset,
        n=args.n,
        seed=args.seed,
        cache_dir=args.cache_dir,
        fallback=not args.no_fallback,
        embedding_resolution=args.embedding_resolution,
        systems=tuple(args.systems.split(",")),
        fresh_extraction=args.fresh_extraction,
    )
    print(f"{summary['label']} | {summary['dataset']} | {summary['question_count']} questions")
    if summary["fallback_reason"]:
        print(f"Fallback: {summary['fallback_reason']}")
    print(path)
    print(args.output_dir / "summary_project3.json")


if __name__ == "__main__":
    main()

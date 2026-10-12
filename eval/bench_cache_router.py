"""Measured cache threshold, router and mixed-workload benchmarks; mock is not a result."""

import argparse
import csv
import json
import random
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from uuid import uuid4

import numpy as np

from app.audit import create_audit_store
from app.auth import issue_token, verify_token
from app.cache import SemanticCache, entity_number_guard, normalize_query
from app.config import ROOT, Settings
from app.contracts import CurrentUser
from app.corpus_state import CorpusState
from app.embed import embed
from app.ingest import document_paths, ingest_acl_documents
from app.logging_db import create_request_store
from app.router import llm_route, rule_route
from app.secure_rag import SecureRAGEngine
from app.service import RAGService
from app.vectorstore import create_client
from eval.judge import judge
from eval.run_eval import load_items


def write_csv(output_dir: Path, tag: str, rows: list[dict]) -> Path:
    """Publish measured rows under a unique, Windows-safe UTC filename."""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{tag}_{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}.csv"
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return path


def sweep(output_dir: Path, limit: int | None = None) -> Path:
    """Evaluate pairwise embedding thresholds 0.85..0.97 with and without the guard."""
    pairs = {}
    for kind, filename in (("good", "paraphrase_pairs.jsonl"), ("bad", "near_miss_pairs.jsonl")):
        rows = [
            json.loads(line)
            for line in (ROOT / "data" / "cache_pairs" / filename)
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        pairs[kind] = rows[:limit] if limit else rows
    observations = {}
    for kind, rows in pairs.items():
        first = embed([normalize_query(row["query_a"]) for row in rows])
        second = embed([normalize_query(row["query_b"]) for row in rows])
        observations[kind] = [
            (float(np.clip(a @ b, -1, 1)), entity_number_guard(row["query_a"], row["query_b"]))
            for row, a, b in zip(rows, first, second, strict=True)
        ]
    measured = []
    for guard in (False, True):
        for percentage in range(85, 98):
            threshold = percentage / 100
            hits = {
                kind: sum(score >= threshold and (not guard or passes) for score, passes in values)
                for kind, values in observations.items()
            }
            measured.append(
                {
                    "mode": Settings().mode.upper(),
                    "guard": int(guard),
                    "threshold": threshold,
                    "good_pairs": len(pairs["good"]),
                    "near_miss_pairs": len(pairs["bad"]),
                    "good_hits": hits["good"],
                    "good_hit_rate": hits["good"] / len(pairs["good"]),
                    "false_hits": hits["bad"],
                    "scope": "pairwise tuning set, not held-out production accuracy",
                }
            )
        safe = [
            row["threshold"]
            for row in measured
            if row["guard"] == int(guard) and row["false_hits"] == 0
        ]
        if safe:
            print(f"guard={guard}: lowest threshold with zero tuning false hits: {min(safe):.2f}")
        else:
            print(
                f"guard={guard}: no zero-false-hit threshold exists. "
                "Enable/review the entity/number guard; action and negation flips "
                "need additional checks."
            )
    return write_csv(output_dir, "cache_sweep", measured)


@contextmanager
def benchmark_context():
    """Create an isolated ACL copy of public sample docs, with real request/audit logging."""
    settings = Settings()
    client, audit, requests = create_client(), None, None
    collection, cache_collection = "project1_" + uuid4().hex, "project1_cache_" + uuid4().hex
    with TemporaryDirectory(prefix="Northwind Project1 ") as temporary:
        try:
            state = CorpusState(Path(temporary) / "state.db")
            documents = [
                {
                    "tenant_id": "benchmark",
                    "doc_id": "benchmark:" + path.relative_to(settings.docs_dir).as_posix(),
                    "source": path.relative_to(settings.docs_dir).as_posix(),
                    "text": path.read_text(encoding="utf-8"),
                    "allowed_roles": ["employee"],
                    "allowed_users": [],
                    "classification": "public",
                }
                for path in document_paths(settings.docs_dir)
            ]
            ingest_acl_documents(documents, client, state, collection=collection)
            audit, requests = create_audit_store(), create_request_store()
            engine = SecureRAGEngine(client, state, audit, collection)
            cache = SemanticCache(client, state, collection=cache_collection)
            user = verify_token(
                issue_token(CurrentUser("benchmark.operator", "benchmark", ("employee",)))
            )
            yield engine, cache, requests, user
        finally:
            for name in (cache_collection, collection):
                if client.collection_exists(name):
                    client.delete_collection(name)
            client.close()
            if audit:
                audit.close()
            if requests:
                requests.close()


def build_workload(items: list, repeat_ratio: float, seed: int = 42) -> list[dict]:
    """Interleave new queries and prior-query repeats; half repeats use a template paraphrase."""
    if not 0 <= repeat_ratio < 1:
        raise ValueError("repeat_ratio must be in [0,1)")
    rng = random.Random(seed)
    remaining = list(items)
    rng.shuffle(remaining)
    repeat_count = round(len(items) * repeat_ratio / (1 - repeat_ratio))
    seen, workload = [], []
    repeats_left = repeat_count
    while remaining or repeats_left:
        repeat = (
            bool(seen)
            and repeats_left > 0
            and (not remaining or rng.random() < repeats_left / (len(remaining) + repeats_left))
        )
        if repeat:
            item = rng.choice(seen)
            question = item.question if repeats_left % 2 == 0 else "Please " + item.question
            repeats_left -= 1
        else:
            item = remaining.pop()
            seen.append(item)
            question = item.question
        workload.append(
            {
                "id": item.id,
                "question": question,
                "reference": item.reference,
                "repeat": int(repeat),
            }
        )
    return workload


def replay(
    service: RAGService, workload: list[dict], user: CurrentUser, run_tag: str, repeat_ratio: float
) -> list[dict]:
    """Record complete service wall time separately from judge time and classifier overhead."""
    measured = []
    for index, item in enumerate(workload):
        start = perf_counter()
        result = service.ask(item["question"], user, run_tag=run_tag)
        elapsed = (perf_counter() - start) * 1000
        verdict = judge(item["question"], result.response["answer"], item["reference"])
        service.requests.set_quality(result.request_id, float(verdict.correct))
        measured.append(
            {
                "mode": Settings().mode.upper(),
                "run_tag": run_tag,
                "request_no": index + 1,
                "id": item["id"],
                "question": item["question"],
                "reference": item["reference"],
                "answer": result.response["answer"],
                "repeat": item["repeat"],
                "repeat_ratio": repeat_ratio,
                "actual_repeat_ratio": sum(row["repeat"] for row in workload) / len(workload),
                "route": result.route,
                "model": result.response["model"],
                "cache_hit": int(result.cache_hit),
                "escalated": int(result.escalated),
                "in_tokens": result.response["in_tokens"],
                "out_tokens": result.response["out_tokens"],
                "cost": result.cost,
                "cost_basis": "estimated at reference prices",
                "correct": int(verdict.correct),
                "judge_method": verdict.method,
                "judge_cost": verdict.cost,
                "latency_ms": elapsed,
                "latency_scope": "service wall time including request logging; excluding judge",
            }
        )
    return measured


def summarize(rows: list[dict]) -> dict[str, float]:
    """Summarize only recorded service calls; zero-quality mock data is not a model result."""
    return {
        "cost": sum(row["cost"] for row in rows),
        "quality": float(np.mean([row["correct"] for row in rows])),
        "p50_latency_ms": float(np.percentile([row["latency_ms"] for row in rows], 50)),
        "p95_latency_ms": float(np.percentile([row["latency_ms"] for row in rows], 95)),
        "cache_hit_rate": float(np.mean([row["cache_hit"] for row in rows])),
        "escalation_rate": float(np.mean([row["escalated"] for row in rows])),
    }


def compare(output_dir: Path, repeat_ratio: float = 0.4, limit: int | None = None) -> Path:
    """Replay the same mixed workload through always-large baseline and cleared-cache service."""
    workload = build_workload(load_items(ROOT / "data" / "eval.jsonl", limit), repeat_ratio)
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    with benchmark_context() as (engine, cache, requests, user):
        baseline = replay(
            RAGService(engine, cache, requests, cache_enabled=False, routing_enabled=False),
            workload,
            user,
            f"p1_baseline_{run_id}",
            repeat_ratio,
        )
        cache.clear()
        routed = replay(
            RAGService(engine, cache, requests),
            workload,
            user,
            f"p1_optimized_{run_id}",
            repeat_ratio,
        )
    paths = [
        write_csv(output_dir, "project1_baseline", baseline),
        write_csv(output_dir, "project1_optimized", routed),
    ]
    original, optimized = summarize(baseline), summarize(routed)
    summary = {
        "mode": Settings().mode.upper(),
        "label": "MOCK (not a result)" if Settings().mode == "mock" else "REAL",
        "repeat_ratio": repeat_ratio,
        "actual_repeat_ratio": sum(item["repeat"] for item in workload) / len(workload),
        "requests_per_system": len(workload),
        "cost_basis": "estimated at reference prices",
        "baseline": original,
        "optimized": optimized,
        "cost_reduction_percent": 100 * (original["cost"] - optimized["cost"]) / original["cost"]
        if original["cost"]
        else None,
        "p50_change_ms": optimized["p50_latency_ms"] - original["p50_latency_ms"],
        "p95_change_ms": optimized["p95_latency_ms"] - original["p95_latency_ms"],
        "quality_delta": optimized["quality"] - original["quality"],
        "cache_hit_rate": optimized["cache_hit_rate"],
        "escalation_rate": optimized["escalation_rate"],
        "csvs": [path.name for path in paths],
    }
    path = output_dir / "summary_project1.json"
    path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return path


def router_benchmark(output_dir: Path, limit: int | None = None) -> list[Path]:
    """Measure both classifiers on labels and both routing policies on reviewed QA references."""
    labels = [
        json.loads(line)
        for line in (ROOT / "data" / "router_labels.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    labels = labels[:limit] if limit else labels
    classification, tradeoff = [], []
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    with benchmark_context() as (engine, cache, requests, user):
        for item in labels:
            chunks = engine.retrieve(item["question"], user, Settings().small_model)
            for method, decision in (
                ("rule", rule_route(item["question"], chunks)),
                ("llm", llm_route(item["question"])),
            ):
                classification.append(
                    {
                        "mode": Settings().mode.upper(),
                        "id": item["id"],
                        "router": method,
                        "question": item["question"],
                        "expected": item["label"],
                        "predicted": decision.route,
                        "correct": int(decision.route == item["label"]),
                        "reason": decision.reason,
                        "classifier_in_tokens": decision.in_tokens,
                        "classifier_out_tokens": decision.out_tokens,
                        "classifier_reference_cost": decision.cost,
                    }
                )
        workload = build_workload(load_items(ROOT / "data" / "eval.jsonl", limit), 0)
        for method in ("baseline", "rule", "llm"):
            service = RAGService(
                engine,
                cache,
                requests,
                cache_enabled=False,
                routing_enabled=method != "baseline",
                router_mode="rule" if method == "baseline" else method,
            )
            rows = replay(service, workload, user, f"p1_router_{method}_{run_id}", 0)
            tradeoff.append(
                {
                    "mode": Settings().mode.upper(),
                    "router": method,
                    "questions": len(rows),
                    **summarize(rows),
                }
            )
    for method in ("rule", "llm"):
        rows = [row for row in classification if row["router"] == method]
        print(f"{method} router accuracy: {np.mean([row['correct'] for row in rows]):.4f}")
    print(json.dumps(tradeoff, indent=2))
    return [
        write_csv(output_dir, "router_accuracy", classification),
        write_csv(output_dir, "router_tradeoff", tradeoff),
    ]


def main() -> None:
    """Run selected experiments, clearly separating mock outputs from real measurements."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sweep", action="store_true")
    parser.add_argument("--router", action="store_true")
    parser.add_argument("--compare", action="store_true")
    parser.add_argument("--repeat-ratio", type=float, default=0.4)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "eval" / "results")
    args = parser.parse_args()
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be positive")
    if Settings().mode == "mock":
        print(
            "MOCK (not a result): fake embeddings/LLM/token counts and reference-price estimates."
        )
    selected = args.sweep or args.router or args.compare
    if args.sweep or not selected:
        print(f"CSV: {sweep(args.output_dir, args.limit)}")
    if args.router or not selected:
        for path in router_benchmark(args.output_dir, args.limit):
            print(f"CSV: {path}")
    if args.compare or not selected:
        print(f"Summary: {compare(args.output_dir, args.repeat_ratio, args.limit)}")


if __name__ == "__main__":
    main()

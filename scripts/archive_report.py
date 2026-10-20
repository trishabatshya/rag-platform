"""Compact README results calculated exclusively from explicitly selected archive artifacts."""

import csv
import json
import math
import re
from pathlib import Path
from statistics import mean

ARCHIVE_MARKER = "<!-- REPORT:ARCHIVED -->"
FILES = {
    "labels": "hand_labels.csv",
    "comparison": "summary_project1_real_threshold090.json",
    "optimized": "project1_optimized_20261017T102733493678Z.csv",
    "sweep": "cache_sweep_20261017T073343622572Z.csv",
    "leakage": "leakage_live_qdrant.txt",
    "graph": "project3_20261019T174828737665Z.csv",
    "graph_summary": "summary_project3_real_final.json",
}


def _csv(directory: Path, key: str, required: set[str]) -> list[dict]:
    if key != "labels":
        required = required | {"mode"}
    with (directory / FILES[key]).open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if not required <= set(reader.fieldnames or []):
            raise ValueError(f"Missing archive columns: {FILES[key]}")
        rows = list(reader)
    if not rows or any(r.get("mode", "REAL") != "REAL" for r in rows):
        raise ValueError(f"Empty/non-real archive: {FILES[key]}")
    return rows


def _number(value: str | float) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Non-finite archived measurement")
    return result


def _link(key: str) -> str:
    name = FILES[key]
    return f"[{name}](results_archive/{name})"


def render_archive_results(directory: Path) -> str:
    """Render compact cited tables; never turn missing history into numeric results."""
    labels = _csv(directory, "labels", {"human_correct", "correct", "reference_in_answer"})
    for row in labels:
        if any(
            row[k] not in {"0", "1"} for k in ("human_correct", "correct", "reference_in_answer")
        ):
            raise ValueError("Review flags must be binary")
    comparison = json.loads((directory / FILES["comparison"]).read_text(encoding="utf-8"))
    graph_summary = json.loads((directory / FILES["graph_summary"]).read_text(encoding="utf-8"))
    if any(summary.get("mode") != "REAL" for summary in (comparison, graph_summary)):
        raise ValueError("Archive summaries must be REAL")
    optimized = _csv(directory, "optimized", {"cache_hit", "reference_in_answer"})
    if any(r[k] not in {"0", "1"} for r in optimized for k in ("cache_hit", "reference_in_answer")):
        raise ValueError("Comparison flags must be binary")
    if FILES["optimized"] not in comparison["csvs"]:
        raise ValueError("Comparison summary/CSV mismatch")
    sweep = _csv(directory, "sweep", {"guard", "threshold", "false_hits", "near_miss_pairs"})
    threshold = int(FILES["comparison"].split("threshold")[1].split(".")[0]) / 100
    guarded = [r for r in sweep if r["guard"] == "1" and _number(r["threshold"]) == threshold]
    if len(guarded) != 1:
        raise ValueError("Guarded sweep threshold is missing or duplicated")
    graph = _csv(directory, "graph", {"system", "kind", "em", "f1", "supporting_recall", "dataset"})
    if {r["system"] for r in graph} != {"vector", "graph_hybrid"} or any(
        r["kind"] != "multihop" for r in graph
    ):
        raise ValueError("Selected archive must contain only the recorded multi-hop systems")
    if graph_summary["csv"] != FILES["graph"] or {r["dataset"] for r in graph} != {
        graph_summary["dataset"]
    }:
        raise ValueError("Graph summary/CSV/corpus mismatch")
    leakage = (directory / FILES["leakage"]).read_text(encoding="utf-8")
    passed = re.search(r"(\d+) passed", leakage)
    if passed is None:
        raise ValueError("Missing live leakage test outcome")
    humans = sum(int(r["human_correct"]) for r in labels)
    agreements = {
        k: 100 * sum(r[k] == r["human_correct"] for r in labels) / len(labels)
        for k in ("reference_in_answer", "correct")
    }
    hits = [r for r in optimized if r["cache_hit"] == "1"]
    correct_hits = sum(int(r["reference_in_answer"]) for r in hits)
    lines = [
        ARCHIVE_MARKER,
        "These tables use the named archived files, not a newer mock run. Rounded values are "
        "calculated from those files; reference costs are estimates, not local-model charges.",
        "",
        "### Baseline",
        "",
        "| Measurement | Result | File |",
        "| --- | --- | --- |",
        f"| Manual answer review | {humans} of {len(labels)} correct | {_link('labels')} |",
        "| Agreement with human labels | "
        f"reference_in_answer {agreements['reference_in_answer']:.0f}%; "
        f"local 3B LLM judge {agreements['correct']:.0f}% | {_link('labels')} |",
        "",
        "Baseline/cache answer quality uses reference_in_answer; manual review remains "
        "the quality check, and the LLM judge is secondary.",
        "",
        "### Project 1: semantic caching and routing",
        "",
        "| Measurement | Result | File |",
        "| --- | --- | --- |",
        f"| Comparison run context | CACHE_THRESHOLD={threshold:.2f}; guard on "
        f"| {_link('comparison')} |",
        f"| Guarded full-sweep near misses at {threshold:.2f} | "
        f"{guarded[0]['false_hits']} false hits "
        f"in {guarded[0]['near_miss_pairs']} pairs | {_link('sweep')} |",
        f"| Cache-hit reference correctness | {correct_hits} of {len(hits)} returned the correct "
        f"reference | {_link('optimized')} |",
        "| Estimated reference-cost reduction | "
        f"{_number(comparison['cost_reduction_percent']):.1f}% "
        f"| {_link('comparison')} |",
        f"| Latency increase | p50 +{_number(comparison['p50_change_ms']) / 1000:.1f} s; "
        f"p95 +{_number(comparison['p95_change_ms']) / 1000:.1f} s | {_link('comparison')} |",
        f"| Simple-routed requests escalated | {100 * _number(comparison['escalation_rate']):.0f}% "
        f"| {_link('comparison')} |",
        "",
        "Escalation adds a sequential model call and explains the latency trade-off; the paired "
        f"run does not isolate causality. Models ran locally; costs are reference-price estimates "
        f"({_link('comparison')}, {_link('optimized')}).",
        "",
        "### Project 2: permission-aware retrieval",
        "",
        "| Measurement | Result | File |",
        "| --- | --- | --- |",
        f"| Live-server leakage suite | {passed[1]} passed | {_link('leakage')} |",
        f"| Backend scope | Live Qdrant; deterministic mock embeddings; SQLite audit log "
        f"| {_link('leakage')} |",
        "",
        "### Project 3: public GraphRAG",
        "",
        "| Measurement | Result | File |",
        "| --- | --- | --- |",
    ]
    for system in ("vector", "graph_hybrid"):
        rows = [r for r in graph if r["system"] == system]
        if len(rows) != graph_summary["systems"][system]["all"]["count"]:
            raise ValueError("Graph summary question-count mismatch")
        metrics = "; ".join(
            f"{label} {100 * mean(_number(r[key]) for r in rows):.1f}%"
            for label, key in (
                ("EM", "em"),
                ("F1", "f1"),
                ("supporting-title recall", "supporting_recall"),
            )
        )
        lines.append(f"| {system} | {metrics} | {_link('graph')} |")
    first_fill = graph_summary["indexing"]["first_fill_extraction"]
    if (
        not 0
        <= _number(first_fill["known_chunks"])
        <= _number(graph_summary["indexing"]["paragraph_count"])
    ):
        raise ValueError("Invalid first-fill coverage")
    lines += [
        f"| First-fill indexing coverage | {first_fill['known_chunks']} of "
        f"{graph_summary['indexing']['paragraph_count']} paragraphs measured; total cost unknown "
        f"| {_link('graph_summary')} |",
        f"| Decomposition | NOT YET RUN with {graph_summary['generation_model']}: excluded after "
        f"invalid sub-question lists | {_link('graph_summary')} |",
        "",
        "HotpotQA is multi-hop: no single-hop questions are present in this run, so no single-hop "
        f"result exists ({_link('graph')}, {_link('graph_summary')}). "
        "Indexing cost is partly measured; "
        "recorded elapsed time includes stalls and timeouts from earlier runs, and the extraction "
        f"cache mixes code versions ({_link('graph_summary')}, "
        "[extraction_failures.log](results_archive/extraction_failures.log)).",
    ]
    return "\n".join(lines) + "\n"

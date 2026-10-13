"""Publish measured real rows and separately labeled mock checks into README result markers."""

import argparse
import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, median

import numpy as np

from app.config import ROOT

START = "<!-- RESULTS:START -->"
END = "<!-- RESULTS:END -->"
MOCK = "MOCK (not a result)"
PENDING = "NOT YET RUN"


@dataclass(frozen=True)
class Run:
    """A completed CSV whose rows have one explicit runtime mode."""

    path: Path
    mode: str
    rows: list[dict[str, str]]

    @property
    def order(self) -> tuple[int, str]:
        return self.path.stat().st_mtime_ns, self.path.name


def _mode(value: str) -> str:
    if value == "REAL":
        return "REAL"
    if value in {"MOCK", MOCK}:
        return "MOCK"
    raise ValueError(f"Missing or unknown result mode: {value!r}")


def _number(row: dict, key: str) -> float:
    value = float(row[key])
    if not math.isfinite(value):
        raise ValueError(f"Non-finite measurement: {key}")
    return value


def _runs(directory: Path, prefix: str, required: set[str]) -> list[Run]:
    runs = []
    for path in directory.glob(f"{prefix}_*.csv"):
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if not required <= set(reader.fieldnames or []):
                raise ValueError(f"Missing required fields in {path.name}")
            rows = list(reader)
        if not rows:
            raise ValueError(f"Empty result CSV: {path.name}")
        modes = {_mode(row.get("mode", "")) for row in rows}
        if len(modes) != 1:
            raise ValueError(f"Mixed runtime modes in {path.name}")
        runs.append(Run(path, modes.pop(), rows))
    return sorted(runs, key=lambda run: run.order)


def _latest(runs: list[Run], mode: str) -> Run | None:
    return next((run for run in reversed(runs) if run.mode == mode), None)


def _cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def _source(run: Run | None) -> str:
    return f"`{_cell(run.path.name)}`" if run else PENDING


def _fmt(value: float | None) -> str:
    return f"{value:.4f}" if value is not None else "not recorded"


def _pair_runs(directory: Path) -> list[tuple[Run, Run]]:
    required = {
        "mode",
        "run_tag",
        "request_no",
        "id",
        "question",
        "repeat_ratio",
        "actual_repeat_ratio",
        "cost",
        "correct",
        "latency_ms",
        "cache_hit",
        "escalated",
    }
    baseline = _runs(directory, "project1_baseline", required)
    optimized = _runs(directory, "project1_optimized", required)
    pairs = []
    for b in baseline:
        tags = {row["run_tag"] for row in b.rows}
        if len(tags) != 1 or not next(iter(tags)).startswith("p1_baseline_"):
            raise ValueError(f"Invalid baseline run tags: {b.path.name}")
        expected = "p1_optimized_" + next(iter(tags)).removeprefix("p1_baseline_")
        matches = [
            o
            for o in optimized
            if o.mode == b.mode and {row["run_tag"] for row in o.rows} == {expected}
        ]
        if not matches:
            continue  # An interrupted/unpaired run is not a comparison.
        o = max(matches, key=lambda run: run.order)

        def workload(run: Run) -> list[tuple]:
            return [
                (
                    x["request_no"],
                    x["id"],
                    x["question"],
                    x["repeat_ratio"],
                    x["actual_repeat_ratio"],
                )
                for x in run.rows
            ]

        if workload(b) != workload(o):
            raise ValueError(f"Mismatched paired workloads: {b.path.name}, {o.path.name}")
        pairs.append((b, o))
    return sorted(pairs, key=lambda pair: max(pair[0].order, pair[1].order))


def _indexing(directory: Path, run: Run) -> dict | None:
    candidates = [
        path
        for path in directory.glob("*.json")
        if path.name == "summary_project3.json" or path.name.startswith("project3_")
    ]
    for path in sorted(candidates, key=lambda p: (p.stat().st_mtime_ns, p.name), reverse=True):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("csv") != run.path.name:
            continue  # A newer fixed summary must not supply indexing cost for an older CSV.
        if _mode(data.get("mode", "")) != run.mode:
            raise ValueError(f"Summary/CSV mode mismatch: {path.name}")
        origins = {row["dataset"] for row in run.rows}
        if origins != {data.get("dataset")}:
            raise ValueError(f"Summary/CSV dataset mismatch: {path.name}")
        return data.get("indexing")
    return None


def render_results(directory: Path) -> str:
    """Select latest real and mock artifacts independently; never publish mock numeric metrics."""
    baseline = _runs(directory, "baseline", {"mode", "correct", "hit", "latency_ms", "cost"})
    acl = _runs(directory, "acl", {"mode", "measurement", "overhead_ms", "revoke_to_effect_ms"})
    graph = _runs(
        directory,
        "project3",
        {
            "mode",
            "dataset",
            "system",
            "kind",
            "em",
            "f1",
            "supporting_recall",
            "latency_ms",
            "in_tokens",
            "out_tokens",
            "reference_cost",
        },
    )
    pairs = _pair_runs(directory)
    real_pair = next((p for p in reversed(pairs) if p[0].mode == "REAL"), None)
    mock_pair = next((p for p in reversed(pairs) if p[0].mode == "MOCK"), None)
    real = [
        _latest(baseline, "REAL"),
        real_pair[1] if real_pair else None,
        _latest(acl, "REAL"),
        _latest(graph, "REAL"),
    ]
    mock = [
        _latest(baseline, "MOCK"),
        mock_pair[1] if mock_pair else None,
        _latest(acl, "MOCK"),
        _latest(graph, "MOCK"),
    ]
    lines = [
        "Generated by `python tasks.py report`. Real measurements and mock checks are separate.",
        "Reference costs are USD estimates, not local-model charges.",
        "",
        "| Project | Latest real run | Latest mock check |",
        "| --- | --- | --- |",
    ]
    for name, r, m in zip(
        (
            "Baseline RAG",
            "Project 1: cache and routing",
            "Project 2: permission-aware retrieval",
            "Project 3: GraphRAG",
        ),
        real,
        mock,
        strict=True,
    ):
        lines.append(
            f"| {name} | {'REAL — ' + _source(r) if r else PENDING} | "
            f"{MOCK + ' — ' + _source(m) if m else PENDING} |"
        )

    lines += [
        "",
        "### Baseline RAG",
        "",
        "| Questions | Correctness | Source hit rate | p50 / p95 latency (ms) | "
        "Mean reference answer cost (USD) |",
        "| --- | --- | --- | --- | --- |",
    ]
    b = real[0]
    if b:
        hits = [_number(row, "hit") for row in b.rows if row["hit"] != ""]
        latency = [_number(row, "latency_ms") for row in b.rows]
        lines.append(
            f"| {len(b.rows)} | {_fmt(mean(_number(r, 'correct') for r in b.rows))} | "
            f"{_fmt(mean(hits) if hits else None)} | {_fmt(float(np.percentile(latency, 50)))}"
            f" / {_fmt(float(np.percentile(latency, 95)))} | "
            f"{_fmt(mean(_number(r, 'cost') for r in b.rows))} |"
        )
    else:
        lines.append("| " + " | ".join([PENDING] * 5) + " |")

    lines += [
        "",
        "### Project 1: semantic cache and routing",
        "",
        "| Requests / system | Actual repeat ratio | Reference cost reduction (%) | "
        "Quality delta | Cache hit rate | Escalation rate | p50 / p95 change (ms) |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    if real_pair:
        b, o = real_pair
        original, optimized = (sum(_number(r, "cost") for r in run.rows) for run in (b, o))
        quality = mean(_number(r, "correct") for r in o.rows) - mean(
            _number(r, "correct") for r in b.rows
        )
        change = [
            float(np.percentile([_number(r, "latency_ms") for r in o.rows], q))
            - float(np.percentile([_number(r, "latency_ms") for r in b.rows], q))
            for q in (50, 95)
        ]
        lines.append(
            f"| {len(o.rows)} | {_fmt(_number(o.rows[0], 'actual_repeat_ratio'))} | "
            f"{_fmt(100 * (original - optimized) / original if original else None)} | "
            f"{_fmt(quality)} | {_fmt(mean(_number(r, 'cache_hit') for r in o.rows))} | "
            f"{_fmt(mean(_number(r, 'escalated') for r in o.rows))} | "
            f"{_fmt(change[0])} / {_fmt(change[1])} |"
        )
        lines += [
            "",
            f"Paired baseline: {_source(b)}. Quality is the recorded judge verdict; "
            "latency includes the service and excludes judging.",
        ]
    else:
        lines.append("| " + " | ".join([PENDING] * 7) + " |")

    lines += [
        "",
        "### Project 2: permission-aware multi-tenant retrieval",
        "",
        "| Paired raw vector queries | Median paired filter overhead (ms) | "
        "Revoke-to-effect (ms) |",
        "| --- | --- | --- |",
    ]
    a = real[2]
    if a:
        queries = [r for r in a.rows if r["measurement"] == "filter_pair"]
        revoked = [r for r in a.rows if r["measurement"] == "revoke"]
        if not queries or len(revoked) != 1:
            raise ValueError(f"Incomplete ACL benchmark: {a.path.name}")
        lines.append(
            f"| {len(queries)} | {_fmt(median(_number(r, 'overhead_ms') for r in queries))}"
            f" | {_fmt(_number(revoked[0], 'revoke_to_effect_ms'))} |"
        )
    else:
        lines.append("| " + " | ".join([PENDING] * 3) + " |")
    lines += [
        "",
        "Raw vector timing excludes generation/audit. Offline leakage tests are security "
        "regressions, not a real-model leakage-rate estimate.",
    ]

    lines += [
        "",
        "### Project 3: GraphRAG",
        "",
        "| System / subset | Questions | EM | F1 | Supporting-title recall | "
        "Mean latency (ms) | Mean input / output tokens | Mean reference cost (USD) |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    g = real[3]
    if g and {r["system"] for r in g.rows} != {"vector", "graph_hybrid", "decomposition"}:
        raise ValueError(f"Incomplete GraphRAG comparison: {g.path.name}")
    for system in ("vector", "graph_hybrid", "decomposition"):
        for subset in ("all", "multihop", "singlehop"):
            rows = (
                [
                    r
                    for r in g.rows
                    if r["system"] == system and (subset == "all" or r["kind"] == subset)
                ]
                if g
                else []
            )
            if not g:
                cells = [PENDING] * 7
            elif not rows:
                cells = ["0"] + ["not applicable (empty subset)"] * 6
            else:

                def avg(key: str) -> str:
                    return _fmt(mean(_number(r, key) for r in rows))

                cells = [
                    str(len(rows)),
                    avg("em"),
                    avg("f1"),
                    avg("supporting_recall"),
                    avg("latency_ms"),
                    f"{avg('in_tokens')} / {avg('out_tokens')}",
                    avg("reference_cost"),
                ]
            lines.append(f"| {system} / {subset} | " + " | ".join(cells) + " |")
    if g:
        origins = sorted({r["dataset"] for r in g.rows})
        lines += ["", "Actual data origin: " + ", ".join(_cell(x) for x in origins) + "."]
        indexing = _indexing(directory, g)
        if indexing:
            lines.append(
                "One-time indexing: "
                f"{_fmt(_number(indexing, 'total_indexing_ms'))} ms; "
                f"{_number(indexing, 'in_tokens'):g} input / "
                f"{_number(indexing, 'out_tokens'):g} output tokens; "
                f"USD {_fmt(_number(indexing, 'reference_cost'))} reference extraction cost; "
                f"{_number(indexing, 'cache_hits'):g} reused cache entries. "
                "Excludes embedding/storage/compute charges."
            )
        else:
            lines.append("Indexing usage: not recorded in a matching retained JSON summary.")
    else:
        lines += ["", "One-time real indexing usage/time: " + PENDING + "."]
    return "\n".join(lines) + "\n"


def make_report(
    results_dir: Path = ROOT / "eval" / "results", readme: Path = ROOT / "README.md"
) -> None:
    """Replace exactly one marker region after validating all selected artifacts."""
    text = readme.read_text(encoding="utf-8")
    if text.count(START) != 1 or text.count(END) != 1 or text.index(START) >= text.index(END):
        raise ValueError("README must contain one ordered RESULTS:START/END marker pair")
    body = render_results(results_dir)
    before, rest = text.split(START)
    _, after = rest.split(END)
    updated = before + START + "\n" + body + END + after
    if updated != text:
        readme.write_text(updated, encoding="utf-8")


def main() -> None:
    """Read local artifacts only; no benchmark is launched and no measurements are invented."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", type=Path, default=ROOT / "eval" / "results")
    parser.add_argument("--readme", type=Path, default=ROOT / "README.md")
    args = parser.parse_args()
    make_report(args.results_dir, args.readme)
    print(f"Updated {args.readme}; mock checks remain labeled {MOCK}")


if __name__ == "__main__":
    main()

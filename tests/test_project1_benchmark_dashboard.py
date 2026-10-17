"""Fixture coverage, recorded benchmark arithmetic and headless dashboard execution."""

import csv
import json
import subprocess
import sys
from contextlib import closing

import pytest
from streamlit.testing.v1 import AppTest

from app.config import ROOT
from app.logging_db import RequestEvent, create_request_store
from eval.bench_cache_router import build_workload, summarize
from eval.run_eval import load_items


def test_curated_pair_and_router_fixture_sizes():
    for filename in ("paraphrase_pairs.jsonl", "near_miss_pairs.jsonl"):
        rows = [
            json.loads(line)
            for line in (ROOT / "data" / "cache_pairs" / filename)
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        assert len(rows) >= 50 and len({row["id"] for row in rows}) == len(rows)
        assert all(row["query_a"] != row["query_b"] for row in rows)
    labels = [
        json.loads(line)
        for line in (ROOT / "data" / "router_labels.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(labels) >= 100 and len({row["question"] for row in labels}) == len(labels)
    assert {row["label"] for row in labels} == {"simple", "complex"}


def test_workload_repeat_ratio_and_deterministic_prior_repeats():
    items = load_items(ROOT / "data" / "eval.jsonl")
    first = build_workload(items, 0.4)
    assert first == build_workload(items, 0.4)
    assert sum(row["repeat"] for row in first) / len(first) == 0.4
    seen = set()
    for row in first:
        if row["repeat"]:
            assert row["id"] in seen
        else:
            seen.add(row["id"])
    assert len(seen) == len(items)
    with pytest.raises(ValueError):
        build_workload(items, 1)


def test_benchmark_all_modes_cli_and_summary_reconcile_with_csvs(tmp_path):
    output_dir = tmp_path / "Project1 results with spaces"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tasks.py"),
            "bench-cache",
            "--limit",
            "4",
            "--output-dir",
            str(output_dir),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.count("MOCK (not a result)") >= 3
    summary = json.loads((output_dir / "summary_project1.json").read_text(encoding="utf-8"))
    assert summary["mode"] == "MOCK" and summary["repeat_ratio"] == 0.4
    for system, filename in zip(("baseline", "optimized"), summary["csvs"], strict=True):
        with (output_dir / filename).open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        assert len(rows) == summary["requests_per_system"]
        assert all(row["mode"] == "MOCK" for row in rows)
        assert sum(float(row["cost"]) for row in rows) == pytest.approx(summary[system]["cost"])
        assert (
            sum(int(row["cache_hit"]) for row in rows) / len(rows)
            == summary[system]["cache_hit_rate"]
        )
    assert summary["cost_reduction_percent"] == pytest.approx(
        100
        * (summary["baseline"]["cost"] - summary["optimized"]["cost"])
        / summary["baseline"]["cost"]
    )
    with next(output_dir.glob("cache_sweep_*.csv")).open(encoding="utf-8", newline="") as handle:
        sweep = list(csv.DictReader(handle))
    assert len(sweep) == 30
    assert {float(row["threshold"]) for row in sweep} == {i / 100 for i in range(85, 100)}
    assert all(row["true_paraphrase_hit_rate"] == row["good_hit_rate"] for row in sweep)
    for policy, flag in (("off", "0"), ("on", "1")):
        comparison = summary["citation_policies"][policy]
        with (output_dir / comparison["csv"]).open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        assert all(row["escalate_no_citation"] == flag for row in rows)
        assert all(row["correct"] == row["reference_in_answer"] for row in rows)
        assert all("judge_correct" in row for row in rows)
        assert comparison["optimized"]["quality"] == pytest.approx(
            sum(int(row["reference_in_answer"]) for row in rows) / len(rows)
        )
        assert sum(comparison["optimized"]["route_shares"].values()) == pytest.approx(1)
    assert {row["guard"] for row in sweep} == {"0", "1"}
    assert list(output_dir.glob("router_accuracy_*.csv")) and list(
        output_dir.glob("router_tradeoff_*.csv")
    )


def test_escalation_denominator_and_secondary_judge():
    base = {
        "correct": 1,
        "judge_correct": None,
        "cost": 0,
        "latency_ms": 1,
        "cache_hit": 0,
        "escalated": 0,
        "escalation_reasons": "",
    }
    rows = [
        {
            **base,
            "route": "simple",
            "escalated": 1,
            "escalation_reasons": "weak_retrieval|missing_citation",
        },
        {**base, "route": "simple"},
        {**base, "route": "complex"},
        {**base, "route": "cache", "cache_hit": 1},
    ]
    result = summarize(rows)
    assert result["escalation_rate"] == 0.5
    assert result["route_shares"] == {"simple": 0.5, "complex": 0.25, "cache": 0.25}
    assert result["quality"] == 1 and result["judge_accuracy"] is None
    assert result["judge_unparseable_count"] == 4
    for reason in ("weak_retrieval", "missing_citation"):
        assert result["escalation_reasons"][reason] == {"count": 1, "share_of_simple": 0.5}
    assert summarize([rows[-1]])["escalation_rate"] is None


def test_dashboard_empty_state_runs_without_exception():
    app = AppTest.from_file(ROOT / "dashboard.py", default_timeout=15).run()
    assert not app.exception
    assert "No request measurements" in app.info[0].value


def test_dashboard_mode_and_run_tag_filters_preserve_unknown_quality():
    with closing(create_request_store()) as store:
        store.record(
            RequestEvent(
                "one",
                "acme",
                "question",
                "model",
                "simple",
                False,
                False,
                10,
                2,
                0.1,
                2,
                "first",
                "MOCK",
            )
        )
        store.record(
            RequestEvent(
                "two",
                "acme",
                "question",
                "model",
                "cache",
                True,
                False,
                0,
                0,
                0,
                1,
                "second",
                "MOCK",
            )
        )
        store.set_quality("two", 1)
    app = AppTest.from_file(ROOT / "dashboard.py", default_timeout=15).run()
    assert not app.exception and app.warning
    assert app.metric[-1].value == "2"
    app.selectbox[1].set_value("first").run()
    assert not app.exception and app.metric[-1].value == "1"
    assert any("Quality is unknown" in item.value for item in app.info)

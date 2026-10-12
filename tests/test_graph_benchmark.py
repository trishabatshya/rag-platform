"""End-to-end offline CSV/JSON/review exports on Windows-safe temporary paths."""

import csv
import json

import pytest

from eval.bench_graphrag import run_benchmark
from scripts.failure_analysis import write_failures


def test_benchmark_all_subsets_and_cached_indexing_accounting(tmp_path):
    output = tmp_path / "results with spaces Ω"
    cache = tmp_path / "cache with spaces"
    path, summary = run_benchmark(output, cache_dir=cache)
    assert summary["label"] == "MOCK (not a result)"
    assert summary["question_count"] == 15 and summary["indexing"]["paragraph_count"] == 39
    assert summary["indexing"]["cache_hits"] == 0
    assert summary["indexing"]["in_tokens"] == summary["indexing"]["reference_cost"] == 0
    for system in ("vector", "graph_hybrid", "decomposition"):
        data = summary["systems"][system]
        assert [data[s]["count"] for s in ("all", "multihop", "singlehop")] == [15, 12, 3]
        assert data["all"]["in_tokens"] > 0 and data["all"]["latency_ms"] > 0
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 45 and all(r["mode"] == "MOCK (not a result)" for r in rows)
    assert json.loads((output / "summary_project3.json").read_text(encoding="utf-8")) == summary
    review = (output / "failure_analysis_project3.md").read_text(encoding="utf-8")
    assert "Showing 10 of 12 available failures" in review
    assert "Showing 0 of 0 available failures" in review
    assert "| Failure category |" in review and "MOCK (not a result)" in review
    assert "Raw entities:" in (output / "merge_groups.txt").read_text(encoding="utf-8")
    _, cached = run_benchmark(output, n=1, cache_dir=cache)
    assert cached["indexing"]["cache_hits"] == 39
    assert cached["indexing"]["calls"] == cached["indexing"]["reference_cost"] == 0
    assert cached["systems"]["vector"]["singlehop"]["count"] == 0
    assert cached["systems"]["vector"]["singlehop"]["em"] is None


def test_failure_review_escapes_markdown_and_keeps_category_blank(tmp_path):
    path = tmp_path / "run.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "system",
                "mode",
                "em",
                "supporting_recall",
                "question",
                "gold",
                "predicted",
                "retrieved_titles",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "system": "vector",
                "mode": "MOCK (not a result)",
                "em": 0,
                "supporting_recall": 0,
                "question": "What | happened?\nNext",
                "gold": "gold",
                "predicted": "wrong",
                "retrieved_titles": '["Title"]',
            }
        )
    output = tmp_path / "review.md"
    write_failures(path, output)
    text = output.read_text(encoding="utf-8")
    assert "What \\| happened?<br>Next" in text
    assert "| gold | wrong | Title |  |" in text
    with pytest.raises(ValueError):
        write_failures(path, output, limit=0)


def test_mock_real_dataset_selection_fails_clearly(tmp_path):
    with pytest.raises(ValueError, match="fixture"):
        run_benchmark(tmp_path, source="hotpotqa")

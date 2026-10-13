"""Synthetic temporary artifacts test reporting; none are published as real measurements."""

import csv
import json
import os

import pytest

from scripts.make_report import END, MOCK, PENDING, START, make_report, render_results


def write_csv(directory, name, rows, clock=1):
    path = directory / name
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    os.utime(path, ns=(clock, clock))
    return path


def baseline(mode="REAL", correct=1):
    return [{"mode": mode, "correct": correct, "hit": 1, "latency_ms": 12, "cost": 0.002}]


def graph_rows(mode="REAL", dataset="test-fixture"):
    return [
        {
            "mode": mode,
            "dataset": dataset,
            "system": system,
            "kind": "multihop",
            "em": 1,
            "f1": 1,
            "supporting_recall": 0.5,
            "latency_ms": 10,
            "in_tokens": 100,
            "out_tokens": 2,
            "reference_cost": 0.001,
        }
        for system in ("vector", "graph_hybrid", "decomposition")
    ]


def pair_rows(role, stamp, mode="REAL", cost=1):
    return [
        {
            "mode": mode,
            "run_tag": f"p1_{role}_{stamp}",
            "request_no": 1,
            "id": "q1",
            "question": "Question",
            "repeat_ratio": 0.4,
            "actual_repeat_ratio": 0,
            "cost": cost,
            "correct": 1,
            "latency_ms": 10,
            "cache_hit": 0,
            "escalated": 0,
        }
    ]


def test_empty_results_idempotent_markers_and_windows_unicode_paths(tmp_path):
    directory = tmp_path / "results with spaces Ω"
    directory.mkdir()
    readme = tmp_path / "readme with spaces.md"
    readme.write_text(f"Intro Ω\n{START}\nold\n{END}\nOutro\n", encoding="utf-8")
    make_report(directory, readme)
    text = readme.read_text(encoding="utf-8")
    assert text.startswith("Intro Ω\n" + START)
    assert text.endswith(END + "\nOutro\n")
    assert PENDING in text and MOCK not in text
    make_report(directory, readme)
    assert readme.read_text(encoding="utf-8") == text


def test_mock_numbers_are_never_present_and_pending_real_is_explicit(tmp_path):
    write_csv(tmp_path, "baseline_mock.csv", baseline("MOCK", correct=987654))
    write_csv(tmp_path, "project3_mock.csv", graph_rows(MOCK))
    text = render_results(tmp_path)
    assert MOCK in text and PENDING in text
    assert "987654" not in text and "0.5000" not in text
    assert "baseline_mock.csv" in text and "project3_mock.csv" in text


def test_latest_real_selected_independently_of_newer_mock_and_unrelated_files(tmp_path):
    write_csv(tmp_path, "baseline_old.csv", baseline(correct=0), clock=10)
    write_csv(tmp_path, "baseline_real.csv", baseline(), clock=20)
    write_csv(tmp_path, "baseline_mock.csv", baseline("MOCK"), clock=30)
    (tmp_path / "baseline_incomplete.csv.tmp").write_text("partial", encoding="utf-8")
    (tmp_path / "judge_review.csv").write_text("unrelated", encoding="utf-8")
    text = render_results(tmp_path)
    assert "REAL — `baseline_real.csv`" in text
    assert "baseline_old.csv" not in text and "baseline_mock.csv" in text
    assert "| 1 | 1.0000 | 1.0000 | 12.0000 / 12.0000 | 0.0020 |" in text


def test_comparison_requires_matching_pair_and_reports_actual_csv_metrics(tmp_path):
    write_csv(tmp_path, "project1_baseline_a.csv", pair_rows("baseline", "a", cost=2), clock=10)
    write_csv(tmp_path, "project1_optimized_a.csv", pair_rows("optimized", "a", cost=1), clock=11)
    write_csv(tmp_path, "project1_baseline_incomplete.csv", pair_rows("baseline", "z"), clock=40)
    (tmp_path / "summary_project1.json").write_text(
        '{"mode":"REAL","quality_delta":999}', encoding="utf-8"
    )
    text = render_results(tmp_path)
    assert "50.0000" in text and "project1_optimized_a.csv" in text
    assert "incomplete.csv" not in text and "999" not in text


def test_pair_workload_mismatch_rejected(tmp_path):
    write_csv(tmp_path, "project1_baseline_a.csv", pair_rows("baseline", "a"))
    rows = pair_rows("optimized", "a")
    rows[0]["question"] = "Different workload"
    write_csv(tmp_path, "project1_optimized_a.csv", rows)
    with pytest.raises(ValueError, match="workloads"):
        render_results(tmp_path)


def test_acl_report_measures_paired_overhead_not_difference_of_medians(tmp_path):
    write_csv(
        tmp_path,
        "acl_run.csv",
        [
            {
                "mode": "REAL",
                "measurement": "filter_pair",
                "overhead_ms": 2,
                "revoke_to_effect_ms": "",
            },
            {
                "mode": "REAL",
                "measurement": "filter_pair",
                "overhead_ms": 8,
                "revoke_to_effect_ms": "",
            },
            {"mode": "REAL", "measurement": "revoke", "overhead_ms": "", "revoke_to_effect_ms": 7},
        ],
    )
    assert "| 2 | 5.0000 | 7.0000 |" in render_results(tmp_path)


def test_graph_empty_subset_origin_and_matching_archived_indexing_summary(tmp_path):
    write_csv(tmp_path, "project3_real.csv", graph_rows())
    summary = {
        "mode": "REAL",
        "csv": "project3_real.csv",
        "dataset": "test-fixture",
        "indexing": {
            "total_indexing_ms": 25,
            "in_tokens": 200,
            "out_tokens": 20,
            "reference_cost": 0.04,
            "cache_hits": 3,
        },
    }
    (tmp_path / "project3_real.json").write_text(json.dumps(summary), encoding="utf-8")
    (tmp_path / "summary_project3.json").write_text(
        json.dumps(
            {
                "mode": "MOCK",
                "csv": "different.csv",
                "indexing": {"reference_cost": 999},
            }
        ),
        encoding="utf-8",
    )
    text = render_results(tmp_path)
    assert "test-fixture" in text and "empty subset" in text
    assert "25.0000 ms" in text and "USD 0.0400" in text and "999" not in text


def test_missing_graph_summary_does_not_reuse_stale_indexing(tmp_path):
    write_csv(tmp_path, "project3_real.csv", graph_rows())
    (tmp_path / "summary_project3.json").write_text(
        json.dumps(
            {
                "mode": "REAL",
                "csv": "stale.csv",
                "indexing": {"reference_cost": 999},
            }
        ),
        encoding="utf-8",
    )
    text = render_results(tmp_path)
    assert "not recorded in a matching" in text and "999" not in text


@pytest.mark.parametrize("modes", [[""], ["UNKNOWN"], ["MOCK", "REAL"]])
def test_unknown_missing_or_mixed_modes_fail_before_rewriting(tmp_path, modes):
    write_csv(tmp_path, "baseline_bad.csv", [row for m in modes for row in baseline(m)])
    readme = tmp_path / "README.md"
    original = f"{START}\nunchanged\n{END}"
    readme.write_text(original, encoding="utf-8")
    with pytest.raises(ValueError):
        make_report(tmp_path, readme)
    assert readme.read_text(encoding="utf-8") == original


@pytest.mark.parametrize("text", ["no markers", END + START, START + START + END])
def test_invalid_markers_rejected(tmp_path, text):
    readme = tmp_path / "README.md"
    readme.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="marker"):
        make_report(tmp_path, readme)


def test_nonfinite_real_measurement_and_summary_mode_mismatch_rejected(tmp_path):
    rows = baseline()
    rows[0]["cost"] = "nan"
    path = write_csv(tmp_path, "baseline_bad.csv", rows)
    with pytest.raises(ValueError, match="Non-finite"):
        render_results(tmp_path)
    path.unlink()
    write_csv(tmp_path, "project3_real.csv", graph_rows())
    (tmp_path / "summary_project3.json").write_text(
        json.dumps(
            {
                "mode": "MOCK",
                "csv": "project3_real.csv",
                "dataset": "test-fixture",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="mode mismatch"):
        render_results(tmp_path)

"""Archived README metrics and preservation of editorial text outside the result markers."""

import csv
import json

import pytest

from scripts.archive_report import ARCHIVE_MARKER, FILES, render_archive_results
from scripts.make_report import END, START, make_report


@pytest.fixture
def archived(tmp_path):
    directory = tmp_path / "results_archive"
    directory.mkdir()

    def write(key, rows):
        with (directory / FILES[key]).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    write(
        "labels",
        [
            {"human_correct": 1, "correct": 0, "reference_in_answer": 1},
            {"human_correct": 0, "correct": 0, "reference_in_answer": 1},
        ],
    )
    write("optimized", [{"mode": "REAL", "cache_hit": 1, "reference_in_answer": 1}])
    write(
        "sweep",
        [{"mode": "REAL", "guard": 1, "threshold": 0.9, "false_hits": 2, "near_miss_pairs": 50}],
    )
    write(
        "graph",
        [
            {
                "mode": "REAL",
                "system": system,
                "kind": "multihop",
                "em": 0.5,
                "f1": 0.75,
                "supporting_recall": 1,
                "dataset": "test-fixture",
            }
            for system in ("vector", "graph_hybrid")
        ],
    )
    (directory / FILES["leakage"]).write_text("602 passed, live Qdrant", encoding="utf-8")
    for key, data in {
        "comparison": {
            "mode": "REAL",
            "csvs": [FILES["optimized"]],
            "cost_reduction_percent": 25,
            "p50_change_ms": 4200,
            "p95_change_ms": 22500,
            "escalation_rate": 0.43,
        },
        "graph_summary": {
            "mode": "REAL",
            "csv": FILES["graph"],
            "dataset": "test-fixture",
            "generation_model": "ollama/llama3.2:3b",
            "systems": {s: {"all": {"count": 1}} for s in ("vector", "graph_hybrid")},
            "indexing": {"paragraph_count": 600, "first_fill_extraction": {"known_chunks": 400}},
        },
    }.items():
        (directory / FILES[key]).write_text(json.dumps(data), encoding="utf-8")
    return directory


def test_archived_numbers_are_derived_and_cited(archived):
    text = render_archive_results(archived)
    assert "1 of 2 correct" in text and "reference_in_answer 50%" in text
    assert "LLM judge 50%" in text and "1 of 1 returned the correct reference" in text
    assert "p50 +4.2 s; p95 +22.5 s" in text and "400 of 600 paragraphs" in text
    assert text.count("NOT YET RUN") == 1 and "Decomposition | NOT YET RUN" in text
    for line in text.splitlines():
        if line.startswith("| ") and not line.startswith(("| ---", "| Measurement")):
            assert "results_archive/" in line


def test_archived_report_preserves_editorial_text_and_is_idempotent(archived, tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text(f"Pitch\n{START}\n{ARCHIVE_MARKER}\n{END}\nLimitations", encoding="utf-8")
    make_report(tmp_path / "eval" / "results", readme)
    text = readme.read_text(encoding="utf-8")
    make_report(tmp_path / "eval" / "results", readme)
    assert readme.read_text(encoding="utf-8") == text
    assert text.startswith("Pitch\n") and text.endswith("\nLimitations")


def test_mismatched_archives_fail_before_rewriting(archived, tmp_path):
    path = archived / FILES["graph_summary"]
    data = json.loads(path.read_text(encoding="utf-8"))
    data["csv"] = "unrelated.csv"
    path.write_text(json.dumps(data), encoding="utf-8")
    readme = tmp_path / "README.md"
    original = f"{START}\n{ARCHIVE_MARKER}\n{END}"
    readme.write_text(original, encoding="utf-8")
    with pytest.raises(ValueError, match="mismatch"):
        make_report(tmp_path / "eval" / "results", readme)
    assert readme.read_text(encoding="utf-8") == original

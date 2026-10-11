"""Evaluation metrics, dataset grounding and offline CLI acceptance checks."""

import csv
import json
import subprocess
import sys

import pytest

from app.config import ROOT, Settings, compute_cost
from eval.judge import judge, normalize, token_f1
from eval.judge_check import agreement, sample_judgments
from eval.run_eval import load_items, run_evaluation, summarize


@pytest.mark.parametrize(
    "prediction,reference,expected",
    [
        ("HELLO, world! [1]", "hello world", 1.0),
        ("a a b", "a c", 0.4),
        ("no match", "different words", 0.0),
        ("", "", 1.0),
        ("", "something", 0.0),
        ("14 calendar days [2]", "7 calendar days", 2 / 3),
    ],
)
def test_hand_computed_token_f1(prediction, reference, expected):
    assert token_f1(prediction, reference) == pytest.approx(expected)


def test_mock_judge_threshold_and_no_llm_call(monkeypatch):
    import eval.judge as module

    def forbidden(*args, **kwargs):
        raise AssertionError("Mock judging must not invoke the LLM")

    monkeypatch.setattr(module, "complete", forbidden)
    assert judge("question", "a c", "a b").correct
    assert not judge("question", "a a b", "a c").correct
    assert judge("question", "I don't know", "I don't know").method == "token_f1"


def test_binary_judge_and_usage_accounting(monkeypatch):
    import eval.judge as module
    from app.llm import LLMResult

    monkeypatch.setenv("RAG_MODE", "real")
    model = Settings().judge_model
    monkeypatch.setattr(
        module, "complete", lambda *args, **kwargs: LLMResult("CORRECT", 100, 3, model, 1)
    )
    result = judge("question", "answer", "reference")
    assert result.correct and result.method == "llm"
    assert result.in_tokens == 100 and result.out_tokens == 3
    assert result.cost == compute_cost(model, 100, 3)
    monkeypatch.setattr(
        module, "complete", lambda *args, **kwargs: LLMResult("Perhaps", 1, 1, model, 1)
    )
    with pytest.raises(ValueError, match="invalid verdict"):
        judge("question", "answer", "reference")


def test_sample_corpus_and_eval_are_grounded():
    items = load_items(ROOT / "data" / "eval.jsonl")
    docs = ROOT / "data" / "docs_sample"
    assert len(list(docs.glob("*.md"))) == 20
    assert len(items) >= 40 and sum(not item.answerable for item in items) >= 5
    assert {item.source for item in items if item.answerable} == {
        path.name for path in docs.glob("*.md")
    }
    for item in items:
        if item.answerable:
            assert set(normalize(item.reference)) <= set(
                normalize((docs / item.source).read_text(encoding="utf-8"))
            )


def test_eval_runs_in_mock_mode_and_writes_complete_csv(tmp_path):
    output, summary = run_evaluation(
        ROOT / "data" / "eval.jsonl", tmp_path / "results with spaces", "offline", 4
    )
    with output.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == summary["count"] == 4
    assert all(row["mode"] == "MOCK" and row["judge_method"] == "token_f1" for row in rows)
    assert all(float(row["latency_ms"]) >= 0 and float(row["cost"]) >= 0 for row in rows)
    assert all(row["cost_basis"] == "estimated at reference prices" for row in rows)
    assert all(row["corpus_version"] == "1" for row in rows)
    assert all(json.loads(row["retrieved_sources"]) for row in rows)
    assert not list(output.parent.glob("*.tmp"))


def test_eval_cli_from_unrelated_directory_with_windows_paths(tmp_path):
    output_dir = tmp_path / "My results"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tasks.py"),
            "eval",
            "--tag",
            "cli",
            "--limit",
            "3",
            "--output-dir",
            str(output_dir),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "MOCK (not a result)" in result.stdout
    assert len(list(output_dir.glob("cli_*.csv"))) == 1


def test_summary_excludes_unknown_questions_from_hit_rate():
    summary = summarize(
        [
            {"hit": 1, "correct": 1, "latency_ms": 10, "cost": 0.1},
            {"hit": "", "correct": 0, "latency_ms": 20, "cost": 0.3},
        ]
    )
    assert summary["hit_rate"] == 1
    assert summary["correctness"] == 0.5
    assert summary["p50_latency_ms"] == 15
    assert summary["p95_latency_ms"] == 19.5
    assert summary["mean_reference_cost_usd"] == pytest.approx(0.2)


@pytest.mark.parametrize("tag,limit", [("../escape", None), ("valid", 0), ("valid", -1)])
def test_invalid_eval_arguments(tmp_path, tag, limit):
    with pytest.raises(ValueError):
        run_evaluation(ROOT / "data" / "eval.jsonl", tmp_path, tag, limit)
    assert not list(tmp_path.glob("*.csv"))


def test_unreviewed_candidates_and_duplicate_ids_are_rejected(tmp_path):
    item = {
        "id": "candidate",
        "question": "Question?",
        "reference": "Answer",
        "source": "doc.md",
        "answerable": True,
    }
    path = tmp_path / "items.jsonl"
    path.write_text(json.dumps({**item, "needs_review": True}), encoding="utf-8")
    with pytest.raises(ValueError, match="human-reviewed"):
        load_items(path)
    path.write_text(json.dumps(item) + "\n" + json.dumps(item), encoding="utf-8")
    with pytest.raises(ValueError, match="unique"):
        load_items(path)


def test_reference_price_tiers_and_unknown_model():
    settings = Settings()
    assert compute_cost(settings.large_model, 1_000_000, 0) == 2.5
    assert compute_cost(settings.small_model, 0, 1_000_000) == 0.6
    with pytest.raises(ValueError, match="No reference price"):
        compute_cost("unpriced-model", 100, 100)


def test_human_judge_review_sampling_and_agreement(tmp_path):
    source = tmp_path / "evaluations.csv"
    with source.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["id", "correct"])
        writer.writeheader()
        writer.writerows({"id": i, "correct": int(i % 2 == 0)} for i in range(35))
    first, second = tmp_path / "first.csv", tmp_path / "second.csv"
    assert sample_judgments(source, first) == 30
    sample_judgments(source, second)
    assert first.read_bytes() == second.read_bytes()
    assert agreement(first) == {"total": 30, "reviewed": 0, "agreement": None}
    with pytest.raises(FileExistsError):
        sample_judgments(source, first)
    with first.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fields, rows = reader.fieldnames, list(reader)
    rows[0]["human_verdict"] = "CORRECT" if rows[0]["correct"] == "1" else "INCORRECT"
    rows[1]["human_verdict"] = "INCORRECT" if rows[1]["correct"] == "1" else "CORRECT"
    with first.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    assert agreement(first) == {"total": 30, "reviewed": 2, "agreement": 0.5}

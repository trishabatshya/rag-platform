"""Bounded completion defaults, per-question failures and durable benchmark resume."""

import json
import sys
from types import SimpleNamespace

import pytest

from app.llm import LLMResult, complete
from eval.bench_graphrag import run_benchmark
from eval.graph_checkpoint import append_checkpoint, checkpoint_path, load_checkpoint
from graphrag.dataset import load_fixture
from graphrag.retrieve import GraphPipeline


def test_default_completion_limits_and_explicit_overrides(monkeypatch):
    monkeypatch.setenv("RAG_MODE", "real")
    captured = []

    def provider(**kwargs):
        captured.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="answer"))],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
        )

    monkeypatch.setitem(sys.modules, "litellm", SimpleNamespace(completion=provider))
    complete("planner", "ollama/test", json_mode=True)
    assert captured[-1]["timeout"] == 120 and captured[-1]["max_tokens"] == 400
    assert captured[-1]["num_retries"] == 0
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "7")
    monkeypatch.setenv("LLM_MAX_TOKENS", "33")
    complete("answer", "ollama/test")
    assert captured[-1]["timeout"] == 7 and captured[-1]["max_tokens"] == 33
    complete("extraction", "ollama/test", timeout=90, max_tokens=1000)
    assert captured[-1]["timeout"] == 90 and captured[-1]["max_tokens"] == 1000


@pytest.mark.parametrize(
    "error", [TimeoutError("one slow request"), RuntimeError("generation failed")]
)
def test_question_failure_continues_and_resume_skips_terminal_results(monkeypatch, tmp_path, error):
    original = GraphPipeline.answer
    calls = []

    def answer(self, question, *args, **kwargs):
        calls.append(question)
        if len(calls) == 1:
            raise error
        return original(self, question, *args, **kwargs)

    monkeypatch.setattr(GraphPipeline, "answer", answer)
    _, summary = run_benchmark(tmp_path, n=2, cache_dir=tmp_path / "cache")
    assert len(calls) == 4
    assert summary["selected_systems"] == ["vector", "graph_hybrid"]
    assert summary["systems"]["vector"]["completed"] == 1
    assert summary["systems"]["vector"]["failed"] == 1
    assert summary["systems"]["vector"]["timed_out"] == int(isinstance(error, TimeoutError))
    assert summary["systems"]["graph_hybrid"]["completed"] == 2
    lines = (tmp_path / summary["checkpoint"]).read_text(encoding="utf-8").splitlines()
    rows = [json.loads(line) for line in lines]
    assert len(rows) == 4 and rows[0]["status"] == "failed"
    assert str(error) in rows[0]["failure_reason"] and rows[0]["in_tokens"] is None

    def forbidden(*args, **kwargs):
        raise AssertionError("Finished checkpoint results must not generate again")

    monkeypatch.setattr(GraphPipeline, "answer", forbidden)
    _, resumed = run_benchmark(tmp_path, n=2, cache_dir=tmp_path / "cache")
    assert resumed["resumed_results"] == 4 and resumed["new_results"] == 0
    assert resumed["systems"] == summary["systems"]


def test_interruption_retains_first_result_and_resumes_remaining(monkeypatch, tmp_path):
    original = GraphPipeline.answer
    calls = []

    def interrupt(self, question, *args, **kwargs):
        calls.append(question)
        if len(calls) == 2:
            raise KeyboardInterrupt()
        return original(self, question, *args, **kwargs)

    monkeypatch.setattr(GraphPipeline, "answer", interrupt)
    with pytest.raises(KeyboardInterrupt):
        run_benchmark(tmp_path, n=2, cache_dir=tmp_path / "cache")
    checkpoint = next(tmp_path.glob("graph_checkpoint_*.jsonl"))
    assert len(checkpoint.read_text(encoding="utf-8").splitlines()) == 1
    monkeypatch.setattr(GraphPipeline, "answer", original)
    _, summary = run_benchmark(tmp_path, n=2, cache_dir=tmp_path / "cache")
    assert summary["resumed_results"] == 1 and summary["new_results"] == 3


@pytest.mark.parametrize("timeout", [False, True])
def test_invalid_decomposition_is_counted_even_if_fallback_times_out(
    monkeypatch, tmp_path, timeout
):
    monkeypatch.setattr(
        "graphrag.decompose.complete", lambda *a, **kw: LLMResult("bad plan", 1, 1, "test", 1)
    )
    if timeout:

        def fail(*args, **kwargs):
            raise TimeoutError("fallback timed out")

        monkeypatch.setattr(GraphPipeline, "answer", fail)
    _, summary = run_benchmark(tmp_path, n=1, systems=("decomposition",))
    counts = summary["systems"]["decomposition"]
    assert counts["invalid_decomposition"] == 1
    assert counts["timed_out"] == counts["failed"] == int(timeout)
    assert counts["completed"] == int(not timeout)


def test_checkpoint_recovers_partial_tail_and_isolates_settings(monkeypatch, tmp_path):
    path = checkpoint_path(tmp_path, load_fixture(), False)
    row = {"system": "vector", "question_id": "a", "status": "completed"}
    append_checkpoint(path, row)
    with path.open("ab") as handle:
        handle.write(b'{"system":')
    assert load_checkpoint(path) == {("vector", "a"): row}
    append_checkpoint(path, {**row, "question_id": "b"})
    assert len(load_checkpoint(path)) == 2
    monkeypatch.setenv("LLM_MAX_TOKENS", "123")
    assert checkpoint_path(tmp_path, load_fixture(), False) != path


@pytest.mark.parametrize("systems", [(), ("bad",), ("vector", "vector")])
def test_invalid_systems_fail_before_indexing(tmp_path, systems):
    with pytest.raises(ValueError, match="systems"):
        run_benchmark(tmp_path, systems=systems)

"""Extraction token limits and durable per-chunk failure diagnostics."""

import json
import sys
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.llm import LLMResult, complete
from eval.bench_graphrag import run_benchmark
from graphrag.dataset import load_fixture
from graphrag.extract import ExtractionUnavailable, Extractor


@pytest.mark.parametrize("finish_reason", [None, "length"])
def test_truncated_json_skips_only_one_chunk_and_forwards_limit(
    monkeypatch, tmp_path, finish_reason
):
    monkeypatch.setenv("RAG_MODE", "real")
    monkeypatch.setenv("EXTRACT_MAX_TOKENS", "123")
    first, second = load_fixture().paragraphs[:2]
    calls = []

    def completion(prompt, model, **kwargs):
        calls.append(kwargs)
        text = '{"entities": [' if len(calls) == 1 else second.annotation.model_dump_json()
        return LLMResult(text, 10, 5, model, 1, finish_reason if len(calls) == 1 else None)

    monkeypatch.setattr("graphrag.extract.complete", completion)
    extractor = Extractor(tmp_path / "cache with spaces")
    assert extractor.extract(first) is None
    assert extractor.extract(second) == second.annotation
    assert len(calls) == 2 and all(c["max_tokens"] == 123 for c in calls)
    assert extractor.usage.skipped_chunk_details == [
        {"chunk_id": first.id, "reason": "truncated JSON", "attempts": 1}
    ]
    assert extractor.usage.skipped_chunks == 1 and extractor.usage.calls == 2
    assert len(list(extractor.cache_dir.glob("*.json"))) == 1
    # The skipped paragraph remains eligible on a later run.
    monkeypatch.setattr(
        "graphrag.extract.complete",
        lambda prompt, model, **kwargs: LLMResult(
            first.annotation.model_dump_json(), 1, 1, model, 1
        ),
    )
    assert Extractor(extractor.cache_dir).extract(first) == first.annotation


def test_max_tokens_reaches_provider_without_affecting_other_calls(monkeypatch):
    monkeypatch.setenv("RAG_MODE", "real")
    captured = []

    def provider(**kwargs):
        captured.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="{"), finish_reason="length")],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=700),
        )

    monkeypatch.setitem(sys.modules, "litellm", SimpleNamespace(completion=provider))
    assert complete("extract", "ollama/test", max_tokens=700).finish_reason == "length"
    assert captured[-1]["max_tokens"] == 700
    complete("ordinary", "ollama/test")
    assert captured[-1]["max_tokens"] == 400


def test_benchmark_summary_and_skipped_file_record_validation_failure(monkeypatch, tmp_path):
    corpus = load_fixture()
    bad = replace(corpus.paragraphs[0], annotation=None)
    corpus = replace(corpus, paragraphs=[bad, *corpus.paragraphs[1:]])
    monkeypatch.setattr("eval.bench_graphrag.load_dataset_corpus", lambda *a, **kw: corpus)
    output = tmp_path / "results with spaces"
    _, summary = run_benchmark(output, cache_dir=tmp_path / "cache")
    details = summary["indexing"]["skipped_chunk_details"]
    assert details == [{"chunk_id": bad.id, "reason": "validation failure", "attempts": 3}]
    lines = (output / "skipped_chunks.txt").read_text(encoding="utf-8").splitlines()
    assert lines[0] == "MOCK (not a result)" and json.loads(lines[1]) == details[0]
    assert summary["indexing"]["skipped_reasons"] == {"validation failure": 1}


def test_timeout_abort_persists_summary_and_skipped_file(monkeypatch, tmp_path):
    monkeypatch.setenv("RAG_MODE", "real")

    def fail(*args, **kwargs):
        raise TimeoutError("test timeout")

    monkeypatch.setattr("graphrag.extract.complete", fail)
    with pytest.raises(ExtractionUnavailable):
        run_benchmark(tmp_path, cache_dir=tmp_path / "cache")
    summary = json.loads((tmp_path / "summary_project3.json").read_text(encoding="utf-8"))
    assert summary["completed"] is False and "csv" not in summary
    assert summary["indexing"]["skipped_reasons"] == {"timeout": 1}
    lines = (tmp_path / "skipped_chunks.txt").read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[1])["reason"] == "timeout"
    assert not list((tmp_path / "cache").glob("*.json"))

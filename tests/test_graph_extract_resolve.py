"""Strict schema, retries, cache invalidation, accounting and typed resolution regressions."""

from dataclasses import replace

import pytest
from pydantic import ValidationError

from app.llm import LLMResult
from graphrag.dataset import load_fixture
from graphrag.extract import ExtractionUnavailable, Extractor
from graphrag.resolve import resolve
from graphrag.schema import Entity, Extraction


def test_schema_rejects_unknown_types_relations_endpoints_and_extra_fields():
    data = load_fixture().paragraphs[0].annotation.model_dump()
    for change in ("entity", "relation", "endpoint", "extra"):
        candidate = load_fixture().paragraphs[0].annotation.model_dump()
        if change == "entity":
            candidate["entities"][0]["type"] = "FILMMAKER"
        elif change == "relation":
            candidate["relations"][0]["type"] = "INVENTED"
        elif change == "endpoint":
            candidate["entities"] = []
        else:
            candidate["surprise"] = 1
        with pytest.raises(ValidationError):
            Extraction.model_validate(candidate)
    assert Extraction.model_validate(data).relations
    with pytest.raises(ValidationError):
        Entity(name="   ", type="PERSON")


def test_disk_cache_reopens_with_spaces_unicode_and_invalidates_inputs(tmp_path):
    directory = tmp_path / "cache with spaces Ω"
    chunk = load_fixture().paragraphs[0]
    first = Extractor(directory)
    assert first.extract(chunk) == chunk.annotation
    assert first.usage.cache_hits == 0 and first.usage.in_tokens == 0
    second = Extractor(directory)
    assert second.extract(chunk) == chunk.annotation
    assert second.usage.cache_hits == 1
    assert second.extract(replace(chunk, text=chunk.text + " More.")) == chunk.annotation
    assert second.usage.cache_hits == 1
    alternate = Extractor(directory, model="different mock model")
    alternate.extract(chunk)
    assert alternate.usage.cache_hits == 0
    assert len(list(directory.glob("*.json"))) == 3


def test_corrupt_cache_rebuild_and_missing_annotations_skip(tmp_path, caplog):
    chunk = load_fixture().paragraphs[0]
    extractor = Extractor(tmp_path)
    extractor.extract(chunk)
    next(tmp_path.glob("*.json")).write_text("bad", encoding="utf-8")
    assert Extractor(tmp_path).extract(chunk) == chunk.annotation
    missing = Extractor(tmp_path)
    assert missing.extract(replace(chunk, annotation=None)) is None
    assert missing.usage.skipped_chunks == 1
    assert "Skipping" in caplog.text


def test_two_retries_usage_includes_invalid_json_and_disk_hit_costs_zero(monkeypatch, tmp_path):
    monkeypatch.setenv("RAG_MODE", "real")
    chunk = load_fixture().paragraphs[0]
    calls = []

    def completion(prompt, model, **kwargs):
        calls.append(prompt)
        text = "invalid" if len(calls) < 3 else chunk.annotation.model_dump_json()
        return LLMResult(text, 10, 5, model, 1)

    monkeypatch.setattr("graphrag.extract.complete", completion)
    extractor = Extractor(tmp_path)
    assert extractor.extract(chunk) == chunk.annotation
    assert len(calls) == 3
    assert extractor.usage.calls == 3 and extractor.usage.in_tokens == 30
    assert extractor.usage.out_tokens == 15 and extractor.usage.reference_cost > 0
    cached = Extractor(tmp_path)
    cached.extract(chunk)
    assert cached.usage.cache_hits == 1 and cached.usage.reference_cost == 0
    assert cached.usage.calls == cached.usage.in_tokens == cached.usage.out_tokens == 0


def test_provider_errors_skip_after_three_attempts_and_modes_do_not_share_cache(
    monkeypatch, tmp_path
):
    chunk = load_fixture().paragraphs[0]
    Extractor(tmp_path).extract(chunk)
    monkeypatch.setenv("RAG_MODE", "real")
    attempts = []

    def fail(*args, **kwargs):
        attempts.append(1)
        raise OSError("provider offline")

    monkeypatch.setattr("graphrag.extract.complete", fail)
    extractor = Extractor(tmp_path)
    assert extractor.extract(chunk) is None
    assert len(attempts) == 3 and extractor.usage.skipped_chunks == 1
    assert extractor.usage.cache_hits == 0


@pytest.mark.parametrize("error", [TimeoutError("slow"), ConnectionError("offline")])
def test_outage_aborts_after_three_calls_without_caching(monkeypatch, tmp_path, error):
    monkeypatch.setenv("RAG_MODE", "real")
    monkeypatch.setenv("EXTRACT_TIMEOUT_SECONDS", "12")
    calls = []

    def fail(*args, **kwargs):
        calls.append(kwargs)
        raise error

    monkeypatch.setattr("graphrag.extract.complete", fail)
    extractor = Extractor(tmp_path)
    with pytest.raises(ExtractionUnavailable, match="3 consecutive.*Check Ollama"):
        extractor.extract(load_fixture().paragraphs[0])
    assert len(calls) == 3 and all(call["timeout"] == 12 for call in calls)
    assert extractor.usage.failed_chunks == extractor.usage.skipped_chunks == 1
    assert not list(tmp_path.glob("*.json"))


def test_completed_call_resets_timeout_streak_and_failed_chunk_is_retried(monkeypatch, tmp_path):
    monkeypatch.setenv("RAG_MODE", "real")
    chunk = load_fixture().paragraphs[0]
    outcomes = iter([TimeoutError(), TimeoutError(), "bad", chunk.annotation.model_dump_json()])

    def completion(prompt, model, **kwargs):
        value = next(outcomes)
        if isinstance(value, Exception):
            raise value
        return LLMResult(value, 1, 1, model, 1)

    monkeypatch.setattr("graphrag.extract.complete", completion)
    extractor = Extractor(tmp_path)
    assert extractor.extract(chunk) is None
    assert extractor.consecutive_timeouts == 0 and extractor.usage.failed_chunks == 1
    assert not list(tmp_path.glob("*.json"))
    assert Extractor(tmp_path).extract(chunk) == chunk.annotation


@pytest.mark.parametrize("invalid_type", [False, True])
def test_only_dangling_relations_are_salvaged(monkeypatch, tmp_path, invalid_type):
    import json

    monkeypatch.setenv("RAG_MODE", "real")
    chunk = load_fixture().paragraphs[0]
    payload = chunk.annotation.model_dump()
    dangling = dict(payload["relations"][0])
    dangling["target"] = {"name": "Undeclared place", "type": "PLACE"}
    if invalid_type:
        dangling["type"] = "INVENTED"
    payload["relations"].append(dangling)
    monkeypatch.setattr(
        "graphrag.extract.complete",
        lambda prompt, model, **kwargs: LLMResult(json.dumps(payload), 10, 5, model, 1),
    )
    extractor = Extractor(tmp_path)
    result = extractor.extract(chunk)
    assert result == chunk.annotation
    assert extractor.usage.kept_relations == len(chunk.annotation.relations)
    assert extractor.usage.dropped_relations == 1 and extractor.usage.failed_chunks == 0
    assert extractor.usage.repaired_relation_types == int(invalid_type)
    cached = Extractor(tmp_path)
    assert cached.extract(chunk) == result
    assert cached.usage.cache_hits == 1 and cached.usage.dropped_relations == 0


def test_extraction_timeout_disables_nested_provider_retries(monkeypatch):
    import sys
    from types import SimpleNamespace

    from app.llm import complete

    monkeypatch.setenv("RAG_MODE", "real")
    captured = []

    def provider(**kwargs):
        captured.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
        )

    monkeypatch.setitem(sys.modules, "litellm", SimpleNamespace(completion=provider))
    complete("extract", "ollama/test", timeout=90)
    assert captured[-1]["timeout"] == 90 and captured[-1]["num_retries"] == 0
    complete("ordinary", "ollama/test")
    assert captured[-1]["timeout"] == 120 and captured[-1]["num_retries"] == 0


def test_typed_resolution_alias_longest_canonical_and_review_report(tmp_path):
    long = Entity(name="Christopher Nolan", type="PERSON")
    short = Entity(name="Chris Nolan", type="PERSON")
    other = Entity(name="Christopher Norton", type="PERSON")
    place = Entity(name="Chris Nolan", type="PLACE")
    resolution = resolve([long, short, other, place, short])
    assert resolution.mapping[short] == long
    assert resolution.mapping[other] == other
    assert resolution.mapping[place] == place
    path = tmp_path / "human review" / "merge_groups.txt"
    resolution.report(path, "mock")
    text = path.read_text(encoding="utf-8")
    assert "Raw entities: 4" in text and "Canonical entities: 3" in text
    assert "Chris Nolan" in text and "MOCK (not a result)" in text


def test_subset_name_risk_is_visible_and_optional_embeddings_are_opt_in(monkeypatch):
    names = [
        Entity(name="John Smith", type="PERSON"),
        Entity(name="John Adam Smith", type="PERSON"),
    ]
    assert len(set(resolve(names).mapping.values())) == 1  # Documented false-merge risk.
    calls = []

    def vectors(texts):
        import numpy as np

        calls.append(texts)
        return np.tile([1.0, 0.0], (len(texts), 1))

    monkeypatch.setattr("graphrag.resolve.embed", vectors)
    distinct = [Entity(name="Ada Grey", type="PERSON"), Entity(name="Zoe Pike", type="PERSON")]
    assert len(set(resolve(distinct).mapping.values())) == 2 and not calls
    assert len(set(resolve(distinct, embedding_pass=True).mapping.values())) == 1
    assert calls

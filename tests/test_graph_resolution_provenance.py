"""Subset-safe typed resolution and honest original extraction-cost provenance."""

import pytest

from app.llm import LLMResult
from eval.bench_graphrag import run_benchmark
from graphrag.dataset import load_fixture
from graphrag.extract import Extractor
from graphrag.resolve import resolve
from graphrag.schema import Entity


@pytest.mark.parametrize(
    "short,long,kind",
    [
        ("Wisconsin", "Wisconsin Board of Supervisors", "PLACE"),
        ("Kentucky", "Kentucky militiamen", "PLACE"),
        ("United States", "United States Army Training and Doctrine Command", "ORG"),
        ("Biathlon", "Biathlon World Championships", "EVENT"),
        ("A Christmas Carol", "A Klingon Christmas Carol", "WORK"),
        ("International Research Center", "International Research Centers", "ORG"),
    ],
)
def test_subsets_do_not_merge_but_plain_ratio_allows_close_spelling(short, long, kind):
    entities = [Entity(name=short, type=kind), Entity(name=long, type=kind)]
    result = resolve(entities)
    expected = 1 if long.endswith("Centers") else 2
    assert len(set(result.mapping.values())) == expected
    assert sum(result.merge_counts.values()) == 2 - expected


def test_person_first_last_subset_only_and_type_separation():
    pairs = [
        ("John Smith", "John Adam Smith", True),
        ("John Smith", "John Adam Paul Smith", True),
        ("John", "John Smith", False),
        ("Smith", "John Smith", False),
        ("John Smith", "John Smith Jr", False),
    ]
    for short, long, merges in pairs:
        entities = [Entity(name=short, type="PERSON"), Entity(name=long, type="PERSON")]
        result = resolve(entities)
        assert len(set(result.mapping.values())) == (1 if merges else 2)
        assert result.merge_counts["person_first_last"] == int(merges)
    separated = resolve([Entity(name="John Smith", type=t) for t in ("PERSON", "PLACE")])
    assert len(set(separated.mapping.values())) == 2


def test_embedding_pass_cannot_bypass_subset_guard(monkeypatch):
    import numpy as np

    monkeypatch.setattr(
        "graphrag.resolve.embed", lambda texts: np.tile([1.0, 0.0], (len(texts), 1))
    )
    result = resolve(
        [
            Entity(name="Wisconsin", type="PLACE"),
            Entity(name="Wisconsin Board of Supervisors", type="PLACE"),
        ],
        embedding_pass=True,
    )
    assert len(set(result.mapping.values())) == 2 and result.merge_counts["embedding"] == 0


def test_first_fill_cost_survives_cache_hits_and_fresh_extraction(monkeypatch, tmp_path):
    monkeypatch.setenv("RAG_MODE", "real")
    chunk = load_fixture().paragraphs[0]
    calls = []

    def completion(prompt, model, **kwargs):
        calls.append(1)
        text = "invalid" if len(calls) == 1 else chunk.annotation.model_dump_json()
        return LLMResult(text, 10, 5, model, 1)

    monkeypatch.setattr("graphrag.extract.complete", completion)
    first = Extractor(tmp_path)
    assert first.extract(chunk) == chunk.annotation
    original = first.first_fill_summary()
    assert original["in_tokens"] == 20 and original["out_tokens"] == 10
    assert original["elapsed_ms"] > 0 and original["reference_cost"] > 0
    cached = Extractor(tmp_path)
    cached.extract(chunk)
    assert cached.usage.in_tokens == 0 and cached.usage.cache_hits == 1
    assert cached.first_fill_summary() == original
    fresh = Extractor(tmp_path, fresh_extraction=True)
    fresh.extract(chunk)
    assert fresh.usage.calls == 1 and fresh.usage.cache_hits == 0
    assert fresh.usage.in_tokens == 10 and fresh.first_fill_summary() == original
    assert len(calls) == 3


def test_legacy_first_fill_remains_unknown_even_after_forced_regeneration(monkeypatch, tmp_path):
    chunk = load_fixture().paragraphs[0]
    Extractor(tmp_path).extract(chunk)
    next((tmp_path / "provenance").glob("*.json")).unlink()
    for fresh in (False, True):
        extractor = Extractor(tmp_path, fresh_extraction=fresh)
        extractor.extract(chunk)
        history = extractor.first_fill_summary()
        assert history["unknown_chunks"] == 1 and history["known_chunks"] == 0
        assert history["elapsed_ms"] is history["in_tokens"] is history["reference_cost"] is None


def test_benchmark_fresh_option_preserves_history_and_summarizes_merge_reasons(tmp_path):
    cache, output = tmp_path / "cache", tmp_path / "results"
    _, initial = run_benchmark(output, n=1, cache_dir=cache)
    _, cached = run_benchmark(output, n=1, cache_dir=cache)
    _, fresh = run_benchmark(output, n=1, cache_dir=cache, fresh_extraction=True)
    history = initial["indexing"]["first_fill_extraction"]
    assert history["elapsed_ms"] > 0 and history["unknown_chunks"] == 0
    assert cached["indexing"]["first_fill_extraction"] == history
    assert fresh["indexing"]["first_fill_extraction"] == history
    assert cached["indexing"]["cache_hits"] == 39
    assert fresh["indexing"]["cache_hits"] == 0 and fresh["indexing"]["chunks_attempted"] == 39
    indexing = fresh["indexing"]
    assert (
        sum(indexing["merge_counts"].values())
        == indexing["raw_entities"] - indexing["canonical_entities"]
    )
    assert indexing["fresh_extraction"] is True

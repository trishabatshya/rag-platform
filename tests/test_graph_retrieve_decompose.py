"""Fixture sanity acceptance, prompt bounds, no label leakage, and sequential decomposition."""

import json
from dataclasses import replace

import pytest
from pydantic import ValidationError

from app.llm import LLMResult
from graphrag.dataset import load_fixture
from graphrag.decompose import Plan, answer_decomposed
from graphrag.index import build_index
from graphrag.metrics import supporting_recall
from graphrag.resolve import resolve
from graphrag.retrieve import link_entities, rerank
from graphrag.schema import Entity


def test_fixture_hybrid_supporting_recall_meets_vector_acceptance(tmp_path):
    corpus = load_fixture()
    pipeline, usage = build_index(corpus, cache_dir=tmp_path / "cache")
    try:
        vector, hybrid = [], []
        for q in corpus.questions:
            baseline = pipeline.answer(q.question, "vector")
            result = pipeline.answer(q.question, "graph_hybrid")
            vector.append(supporting_recall(baseline["sources"], q.supporting_titles))
            hybrid.append(supporting_recall(result["sources"], q.supporting_titles))
            assert set(result) == {
                "answer",
                "sources",
                "chunks",
                "model",
                "in_tokens",
                "out_tokens",
                "latency_ms",
            }
            assert len(result["chunks"]) <= 6
        assert sum(hybrid) / len(hybrid) >= sum(vector) / len(vector)
        assert usage["skipped_chunks"] == 0 and usage["paragraph_count"] == 39
    finally:
        pipeline.store.close()


def test_hybrid_prompt_has_six_chunks_ten_supported_triples_and_no_gold(monkeypatch, tmp_path):
    corpus = load_fixture()
    pipeline, _ = build_index(corpus, cache_dir=tmp_path)
    captured = []

    def completion(prompt, model, **kwargs):
        captured.append(json.loads(prompt))
        return LLMResult("test", 10, 1, model, 1)

    monkeypatch.setattr("graphrag.retrieve.complete", completion)
    try:
        pipeline.answer("Where was the director of Amber Signal born?")
        data = captured[0]
        ids = {p["id"] for p in data["paragraphs"]}
        assert len(ids) <= 6 and len(data["triples"]) <= 10
        assert data["triples"] and all(t["chunk_id"] in ids for t in data["triples"])
        assert "answer" not in data and "supporting_titles" not in data
    finally:
        pipeline.store.close()


def test_gold_answer_and_support_title_changes_do_not_change_pipeline(tmp_path):
    corpus = load_fixture()
    poisoned = replace(
        corpus,
        questions=[
            replace(q, answer="POISON", supporting_titles=["POISON"]) for q in corpus.questions
        ],
    )
    pipeline, _ = build_index(poisoned, cache_dir=tmp_path)
    try:
        assert (
            pipeline.answer("Where was the director of Amber Signal born?")["answer"] == "Cedar Bay"
        )
        assert pipeline.answer("Who directed Missing Film?")["answer"] == "I don't know"
        with pytest.raises(ValueError):
            pipeline.retrieve("question", "unknown")
    finally:
        pipeline.store.close()


def test_alias_linking_matches_whole_names_and_different_types():
    a = Entity(name="Chris Nolan", type="PERSON")
    b = Entity(name="Christopher Nolan", type="PERSON")
    c = Entity(name="Christopher Nolan", type="WORK")
    resolution = resolve([a, b, c])
    assert link_entities("Where was Chris Nolan born?", resolution) == [b]
    assert set(link_entities("Tell me about Christopher Nolan", resolution)) == {b, c}
    assert link_entities("Chris Nolanville", resolution) == []


def test_reranker_real_adapter_pairs_and_empty_input(monkeypatch):
    from graphrag.graph_store import Hit

    hits = [Hit(p, 0) for p in load_fixture().paragraphs[:2]]

    class Encoder:
        def predict(self, pairs):
            import numpy as np

            assert len(pairs) == 2 and pairs[0][0] == "question"
            return np.array([0.1, 0.9])

    monkeypatch.setattr("graphrag.retrieve._cross_encoder", Encoder())
    assert rerank("question", hits, "real", 1)[0].paragraph == hits[1].paragraph
    assert rerank("question", [], "real") == []


@pytest.mark.parametrize(
    "steps", [[], ["x"] * 5, [""], ["{answer0}"], ["x", "{answer1}"], ["x", "{secret}"]]
)
def test_plan_rejects_invalid_lengths_and_forward_or_unknown_placeholders(steps):
    with pytest.raises(ValidationError):
        Plan(steps=steps)


def test_decomposition_substitution_usage_and_evidence_are_aggregated(tmp_path):
    corpus = load_fixture()
    pipeline, _ = build_index(corpus, cache_dir=tmp_path)
    try:
        result = answer_decomposed("Where was the director of Amber Signal born?", pipeline)
        assert result["answer"] == "Cedar Bay"
        assert {"Amber Signal", "Mara Vale"} <= set(result["sources"])
        direct = pipeline.answer("Who directed Amber Signal?", "vector")
        assert result["in_tokens"] > direct["in_tokens"]
        assert len({c["id"] for c in result["chunks"]}) == len(result["chunks"])
    finally:
        pipeline.store.close()


def test_invalid_plan_falls_back_and_intermediate_abstention_stops(monkeypatch, tmp_path):
    pipeline, _ = build_index(load_fixture(), cache_dir=tmp_path)
    monkeypatch.setattr(
        "graphrag.decompose.complete",
        lambda *a, **k: LLMResult("invalid", 7, 3, pipeline.settings.large_model, 1),
    )
    try:
        result = answer_decomposed("Where is Lumen Archive located?", pipeline)
        assert result["answer"] == "Clearwater"
        direct = pipeline.answer("Where is Lumen Archive located?", "vector")
        assert result["in_tokens"] == direct["in_tokens"] + 7
        monkeypatch.setattr(
            "graphrag.decompose.complete",
            lambda *a, **k: LLMResult(
                json.dumps({"steps": ["Who directed Missing Film?", "Where was {answer0} born?"]}),
                7,
                3,
                pipeline.settings.large_model,
                1,
            ),
        )
        calls = []
        original = pipeline.answer

        def answer(question, **kwargs):
            calls.append(question)
            return original(question, **kwargs)

        monkeypatch.setattr(pipeline, "answer", answer)
        result = answer_decomposed("original", pipeline)
        assert result["answer"] == "I don't know" and calls == ["Who directed Missing Film?"]
    finally:
        pipeline.store.close()

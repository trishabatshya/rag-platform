"""Offline fixture and installed Hugging Face Dataset API contracts."""

from copy import deepcopy

import pytest
from datasets import Dataset

from graphrag.dataset import from_hotpot, load_dataset_corpus, load_fixture


def sample_row():
    return {
        "id": "sample",
        "question": "Where is the archive?",
        "answer": "Bay",
        "type": "bridge",
        "context": {
            "title": ["Archive", "Distractor"],
            "sentences": [["The archive is in Bay.", "It has books."], ["Unrelated fact."]],
        },
        "supporting_facts": {"title": ["Archive", "Archive"], "sent_id": [0, 1]},
    }


def test_fixture_has_bridges_singlehop_distractors_and_seeded_selection():
    corpus = load_fixture()
    assert sum(q.kind == "multihop" for q in corpus.questions) >= 12
    assert sum(q.kind == "singlehop" for q in corpus.questions) >= 3
    assert len(corpus.paragraphs) == 39
    titles = {p.title for p in corpus.paragraphs}
    assert all(set(q.supporting_titles) <= titles for q in corpus.questions)
    assert all(p.annotation is not None for p in corpus.paragraphs)
    assert [q.id for q in load_fixture(n=5).questions] == [q.id for q in corpus.questions[:5]]
    assert [q.id for q in load_fixture(seed=2).questions] != [q.id for q in corpus.questions]


def test_current_dataset_dict_columns_and_one_chunk_per_paragraph():
    corpus = from_hotpot(list(Dataset.from_list([sample_row()])))
    assert corpus.paragraphs[0].id == "Archive::0"
    assert corpus.paragraphs[0].text == "The archive is in Bay. It has books."
    assert corpus.questions[0].supporting_titles == ["Archive"]
    assert corpus.questions[0].kind == "singlehop"
    assert corpus.paragraphs[0].annotation is None


def test_historical_pair_fields_repeated_titles_and_distinct_paragraph_indices():
    first, second = sample_row(), sample_row()
    first["context"] = [["Archive", ["First paragraph."]], ["Distractor", ["Other."]]]
    first["supporting_facts"] = [["Archive", 0], ["Distractor", 0]]
    second["id"] = "other"
    corpus = from_hotpot([first, second, deepcopy(second)])
    assert {p.id for p in corpus.paragraphs} == {
        "Archive::0",
        "Archive::1",
        "Distractor::0",
        "Distractor::1",
    }
    assert corpus.questions[0].kind == "multihop"


def test_loader_calls_current_api_and_seeded_shuffle(monkeypatch):
    calls = []

    def loader(*args, **kwargs):
        calls.append((args, kwargs))
        return Dataset.from_list([{**sample_row(), "id": str(i)} for i in range(10)])

    monkeypatch.setattr("datasets.load_dataset", loader)
    corpus = load_dataset_corpus("hotpotqa", n=4, seed=7)
    assert len(corpus.questions) == 4
    assert calls == [(("hotpotqa/hotpot_qa", "distractor"), {"split": "validation"})]
    assert [q.id for q in corpus.questions] == [
        q.id for q in load_dataset_corpus("hotpotqa", n=4, seed=7).questions
    ]


def test_offline_fallback_is_explicit_and_strict_option_propagates(monkeypatch):
    def unavailable(*args, **kwargs):
        raise ConnectionError("offline")

    monkeypatch.setattr("datasets.load_dataset", unavailable)
    corpus = load_dataset_corpus("hotpotqa", n=2)
    assert corpus.origin == "fixture" and corpus.fallback_reason == "ConnectionError: offline"
    with pytest.raises(ConnectionError):
        load_dataset_corpus("hotpotqa", fallback=False)


def test_bad_data_is_not_hidden_by_fallback(monkeypatch):
    row = sample_row()
    row["supporting_facts"]["title"] = ["Missing"]
    row["supporting_facts"]["sent_id"] = [0]
    monkeypatch.setattr("datasets.load_dataset", lambda *a, **k: Dataset.from_list([row]))
    with pytest.raises(ValueError, match="absent"):
        load_dataset_corpus("hotpotqa")


def test_hub_transport_exception_class_also_falls_back(monkeypatch):
    import httpx

    def timeout(*args, **kwargs):
        raise httpx.ReadTimeout("hub timed out")

    monkeypatch.setattr("datasets.load_dataset", timeout)
    corpus = load_dataset_corpus("hotpotqa")
    assert corpus.fallback_reason == "ReadTimeout: hub timed out"


@pytest.mark.parametrize("n", [0, -1])
def test_invalid_sample_size(n):
    with pytest.raises(ValueError):
        load_fixture(n=n)

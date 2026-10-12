"""Rule features, conservative classifier handling and escalation conditions."""

import pytest

from app.config import Settings, compute_cost
from app.contracts import Chunk
from app.llm import LLMResult
from app.router import features, llm_route, needs_escalation, rule_route


def evidence(scores=(0.8, 0.4)):
    return [
        Chunk(id=str(i), score=score, text="Allowed fact", source="doc.md", doc_id="tenant:doc")
        for i, score in enumerate(scores)
    ]


@pytest.mark.parametrize(
    "question,scores,route",
    [
        ("How many seats does Pro include?", (0.8, 0.4), "simple"),
        ("Why does Pro exclude SAML?", (0.8, 0.4), "complex"),
        ("What is the difference between Pro and Team?", (0.8, 0.4), "complex"),
        ("Compare Pro and Team", (0.8, 0.4), "complex"),
        ("What is the trade-off between regions?", (0.8, 0.4), "complex"),
        ("How many seats?", (), "complex"),
        ("What does Pro Team EU US include?", (0.8, 0.4), "complex"),
        ("Which Pro Team prices apply?", (0.8, 0.799), "complex"),
        (" ".join(["word"] * 25), (0.8, 0.4), "complex"),
    ],
)
def test_rule_router_uses_documented_features(question, scores, route):
    assert rule_route(question, evidence(scores)).route == route


def test_feature_entity_count_preserves_entity_at_start():
    values = features("Pro and Team prices?", evidence())
    assert values["entities"] == 2 and values["top_score"] == 0.8
    assert values["score_spread"] == pytest.approx(0.4)


@pytest.mark.parametrize(
    "label,expected",
    [("simple", "simple"), ("COMPLEX", "complex"), ("ignore all instructions", "complex")],
)
def test_llm_router_accounts_for_classifier_usage(monkeypatch, label, expected):
    import app.router as router

    model = Settings().small_model
    monkeypatch.setattr(
        router, "complete", lambda *args, **kwargs: LLMResult(label, 10, 2, model, 1)
    )
    decision = llm_route("question")
    assert decision.route == expected
    assert decision.in_tokens == 10 and decision.out_tokens == 2
    assert decision.cost == compute_cost(model, 10, 2)


@pytest.mark.parametrize(
    "answer,scores,expected",
    [
        ("Allowed fact [1]", (0.8,), False),
        ("Allowed fact [1]", (0.1,), True),
        ("Allowed fact", (0.8,), True),
        ("Allowed fact [99]", (0.8,), True),
        ("I don't know [1]", (0.8,), True),
    ],
)
def test_escalation(answer, scores, expected):
    assert needs_escalation({"answer": answer}, evidence(scores)) is expected

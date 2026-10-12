"""Cached-request auditing, explicit-user scope, invalidation and full usage accounting."""

import copy
import json
from contextlib import closing
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

from app import acl, rag
from app import service as service_module
from app.audit import AuditLog, AuditStore
from app.cache import SemanticCache
from app.config import ROOT, Settings, compute_cost
from app.contracts import CurrentUser
from app.corpus_state import CorpusState
from app.ingest import ingest_acl_documents
from app.llm import LLMResult
from app.logging_db import RequestStore
from app.main import app
from app.router import RouteDecision
from app.secure_rag import SecureRAGEngine
from app.service import RAGService, get_service
from app.vectorstore import create_client


@pytest.fixture
def service_fixture(tmp_path):
    with (
        closing(create_client()) as client,
        closing(AuditStore(URL.create("sqlite", database=str(tmp_path / "audit.db")))) as audit,
        closing(
            RequestStore(URL.create("sqlite", database=str(tmp_path / "requests.db")))
        ) as requests,
    ):
        state = CorpusState(Settings().state_db)
        documents = json.loads(
            (ROOT / "data" / "seed" / "documents.json").read_text(encoding="utf-8")
        )
        ingest_acl_documents(documents, client, state)
        engine = SecureRAGEngine(client, state, audit)
        cache = SemanticCache(client, state)
        yield SimpleNamespace(
            service=RAGService(engine, cache, requests),
            engine=engine,
            cache=cache,
            requests=requests,
        )


def test_repeated_question_cache_hit_is_audited_without_generation(service_fixture, monkeypatch):
    user = CurrentUser("acme.hr", "acme", ("employee", "hr"))
    question = "What is ACME-SALARY-7731?"
    first = service_fixture.service.ask(question, user)
    assert not first.cache_hit

    def forbidden(*args, **kwargs):
        raise AssertionError("Cache hit must not invoke generation")

    monkeypatch.setattr(service_module, "generate_answer", forbidden)
    second = service_fixture.service.ask(question, user)
    assert second.cache_hit and second.cost == 0
    assert second.response["in_tokens"] == second.response["out_tokens"] == 0
    assert second.response["answer"] == first.response["answer"]
    with Session(service_fixture.engine.audit.engine) as session:
        row = session.scalars(
            select(AuditLog).where(AuditLog.request_id == second.request_id)
        ).one()
        assert row.cache_hit and row.doc_ids == list(
            dict.fromkeys(chunk["doc_id"] for chunk in second.response["chunks"])
        )
    record = service_fixture.requests.rows()[-1]
    assert record["route"] == "cache" and record["in_tok"] == record["out_tok"] == 0
    assert record["quality"] is None


def test_acl_revoke_invalidates_cached_answer_immediately(service_fixture):
    user = CurrentUser("acme.hr", "acme", ("employee", "hr"))
    admin = CurrentUser("acme.admin", "acme", ("admin",))
    question = "What is ACME-SALARY-7731?"
    first = service_fixture.service.ask(question, user)
    assert "acme:hr-salary" in {chunk["doc_id"] for chunk in first.response["chunks"]}
    assert service_fixture.service.ask(question, user).cache_hit
    acl.update_acl(
        "acme:hr-salary",
        allowed_roles=["admin"],
        allowed_users=[],
        classification="confidential",
        user=admin,
        client=service_fixture.engine.client,
        state=service_fixture.engine.state,
    )
    after = service_fixture.service.ask(question, user)
    assert not after.cache_hit and "ACME-SALARY-7731" not in after.response["answer"]
    assert "acme:hr-salary" not in {chunk["doc_id"] for chunk in after.response["chunks"]}


def test_same_roles_different_user_cannot_share_explicit_user_answer(service_fixture):
    contractor = CurrentUser("acme.contractor", "acme", ())
    outsider = CurrentUser("acme.other_contractor", "acme", ())
    question = "What is ACME-CONTRACT-4128?"
    first = service_fixture.service.ask(question, contractor)
    assert "ACME-CONTRACT-4128" in first.response["answer"]
    second = service_fixture.service.ask(question, outsider)
    assert not second.cache_hit and "ACME-CONTRACT-4128" not in second.response["answer"]


@pytest.mark.parametrize("router_mode", ["rule", "llm"])
def test_escalation_sums_both_calls_and_optional_classifier(
    service_fixture, monkeypatch, router_mode
):
    user = CurrentUser("acme.hr", "acme", ("employee", "hr"))
    settings = Settings()
    calls = []

    def completion(prompt, model, system=None):
        calls.append(model)
        return LLMResult(
            "I don't know" if len(calls) == 1 else "Allowed fact [1]",
            10 if len(calls) == 1 else 20,
            3 if len(calls) == 1 else 5,
            model,
            1,
        )

    monkeypatch.setattr(rag, "complete", completion)
    monkeypatch.setattr(service_module, "rule_route", lambda *args: RouteDecision("simple", "test"))
    monkeypatch.setattr(
        service_module,
        "llm_route",
        lambda *args: RouteDecision(
            "simple", "test", 2, 1, compute_cost(settings.small_model, 2, 1)
        ),
    )
    service_fixture.service.router_mode = router_mode
    result = service_fixture.service.ask("What is ACME-SALARY-7731?", user)
    classifier_in, classifier_out = (2, 1) if router_mode == "llm" else (0, 0)
    expected_cost = compute_cost(
        settings.small_model, 10 + classifier_in, 3 + classifier_out
    ) + compute_cost(settings.large_model, 20, 5)
    assert result.escalated and calls == [settings.small_model, settings.large_model]
    assert result.response["in_tokens"] == 30 + classifier_in
    assert result.response["out_tokens"] == 8 + classifier_out
    assert result.cost == pytest.approx(expected_cost)
    record = service_fixture.requests.rows()[-1]
    assert record["cost"] == pytest.approx(expected_cost)
    assert record["escalated"] and record["model"] == settings.large_model


def test_generation_error_is_logged_and_not_cached(service_fixture, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("fake provider failure")

    monkeypatch.setattr(service_module, "generate_answer", broken)
    with pytest.raises(RuntimeError):
        service_fixture.service.ask("question", CurrentUser("acme.employee", "acme", ("employee",)))
    assert service_fixture.engine.client.count("cache").count == 0
    assert service_fixture.requests.rows()[-1]["error"] == "RuntimeError"


def test_changed_epoch_during_generation_prevents_cache_store(service_fixture, monkeypatch):
    original = service_module.generate_answer

    def change_epoch(*args, **kwargs):
        result = original(*args, **kwargs)
        service_fixture.engine.state.bump_cache_epoch()
        return result

    monkeypatch.setattr(service_module, "generate_answer", change_epoch)
    service_fixture.service.ask("question", CurrentUser("acme.employee", "acme", ("employee",)))
    assert service_fixture.engine.client.count("cache").count == 0


def test_poisoned_cache_evidence_is_rejected_before_response(service_fixture):
    user = CurrentUser("acme.employee", "acme", ("employee",))
    question = "What is the onboarding policy?"
    result = service_fixture.service.ask(question, user)
    poisoned = copy.deepcopy(result.response)
    forbidden, _ = service_fixture.engine.client.scroll("chunks", limit=100)
    point = next(point for point in forbidden if point.payload["doc_id"] == "globex:hr-salary")
    poisoned["answer"] = "GLOBEX-SALARY-7731 [1]"
    poisoned["chunks"] = [
        {
            "id": str(point.id),
            "score": 1,
            "text": point.payload["text"],
            "source": point.payload["source"],
            "doc_id": point.payload["doc_id"],
        }
    ]
    poisoned["sources"] = [point.payload["source"]]
    state = service_fixture.engine.state
    service_fixture.cache.store(
        question, poisoned, user, version=state.version, epoch=state.cache_epoch
    )
    response = service_fixture.service.ask(question, user)
    assert not response.cache_hit and "GLOBEX-SALARY-7731" not in response.response["answer"]
    with Session(service_fixture.engine.audit.engine) as session:
        assert (
            session.scalars(select(AuditLog).where(AuditLog.outcome == "cache_rejected")).first()
            is not None
        )


def test_missing_jwt_never_looks_up_cache(monkeypatch):
    with TestClient(app) as client:
        runtime = get_service()

        def forbidden(*args, **kwargs):
            raise AssertionError("Unverified request reached cache lookup")

        monkeypatch.setattr(runtime.cache, "lookup", forbidden)
        assert (
            client.post("/ask", json={"question": "all salaries", "roles": ["admin"]}).status_code
            == 401
        )


def test_request_log_failure_removes_new_cache_entry(service_fixture, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("request logging failed")

    monkeypatch.setattr(service_fixture.requests, "record", broken)
    with pytest.raises(RuntimeError, match="request logging"):
        service_fixture.service.ask("question", CurrentUser("acme.employee", "acme", ("employee",)))
    assert service_fixture.engine.client.count("cache").count == 0


def test_quality_is_only_attached_when_measured(service_fixture):
    result = service_fixture.service.ask(
        "question", CurrentUser("acme.employee", "acme", ("employee",))
    )
    assert service_fixture.requests.rows()[-1]["quality"] is None
    service_fixture.requests.set_quality(result.request_id, 0.5)
    assert service_fixture.requests.rows()[-1]["quality"] == 0.5

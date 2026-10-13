"""Public graph selection cannot bypass tenant cache, audit or ACL revocation."""

import json

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.contracts import CurrentUser
from app.main import app
from graphrag import pipeline as graph


def test_public_pipeline_uses_environment_mode_and_shared_response_contract(monkeypatch):
    question = "Where was the director of Amber Signal born?"
    for mode in ("vector", "graph_hybrid"):
        monkeypatch.setenv("RETRIEVAL_MODE", mode)
        result = graph.rag_pipeline(question, Settings().large_model)
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
        assert result["answer"] == ("Cedar Bay" if mode == "graph_hybrid" else "I don't know")
        assert graph.get_pipeline().origin == "fixture"


def test_public_pipeline_rejects_identity_before_any_indexing(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Tenant request reached public indexing")

    monkeypatch.setattr(graph, "get_pipeline", forbidden)
    with pytest.raises(PermissionError, match="no ACLs"):
        graph.rag_pipeline("question", "model", CurrentUser("u", "t", ("admin",)))
    with pytest.raises(ValueError, match="empty"):
        graph.rag_pipeline("  ", "model")


def test_owned_graph_reuses_index_and_closes_old_configuration(monkeypatch):
    first = graph.get_pipeline()
    assert graph.get_pipeline() is first
    second = graph.get_pipeline(n=2)
    assert second is not first and not first.store.paragraphs
    graph.close_pipeline()
    assert not second.store.paragraphs
    graph.close_pipeline()
    with pytest.raises(ValueError, match="fixture"):
        graph.get_pipeline("hotpotqa")


def test_graph_cli_prints_actual_origin_mode_and_closes_handles(monkeypatch, capsys):
    monkeypatch.setenv("RETRIEVAL_MODE", "graph_hybrid")
    monkeypatch.setattr(
        graph.argparse.ArgumentParser,
        "parse_args",
        lambda *a: type(
            "Args",
            (),
            {
                "question": "Where was the director of Amber Signal born?",
                "dataset": "fixture",
                "n": 15,
                "seed": 42,
                "no_fallback": True,
            },
        )(),
    )
    graph.main()
    data = json.loads(capsys.readouterr().out)
    assert data["dataset"] == "fixture" and data["mode"] == "MOCK (not a result)"
    assert data["response"]["answer"] == "Cedar Bay" and graph._owned is None


def test_bad_retrieval_mode_fails_configuration(monkeypatch):
    monkeypatch.setenv("RETRIEVAL_MODE", "unfiltered")
    with pytest.raises(ValueError, match="RETRIEVAL_MODE"):
        Settings()


@pytest.mark.parametrize("mode", ["vector", "graph_hybrid"])
def test_http_cache_hit_audit_and_revoke_survive_public_graph_mode(monkeypatch, mode):
    monkeypatch.setenv("RETRIEVAL_MODE", mode)

    def forbidden(*args, **kwargs):
        raise AssertionError("Authenticated /ask must never use the public graph")

    monkeypatch.setattr(graph, "get_pipeline", forbidden)
    with TestClient(app) as client:

        def headers(username):
            login = client.post(
                "/auth/login", json={"username": username, "password": "demo-password"}
            )
            assert login.status_code == 200
            return {"Authorization": "Bearer " + login.json()["access_token"]}

        hr, admin = headers("acme.hr"), headers("acme.admin")
        question = {"question": "What is ACME-SALARY-7731?"}
        first = client.post("/ask", headers=hr, json=question)
        second = client.post("/ask", headers=hr, json=question)
        assert first.status_code == second.status_code == 200
        assert "ACME-SALARY-7731" in second.json()["answer"]
        assert second.json()["in_tokens"] == second.json()["out_tokens"] == 0
        access = client.get("/admin/doc-access/acme:hr-salary", headers=admin).json()
        assert access[0]["cache_hit"] and "acme:hr-salary" in access[0]["doc_ids"]
        revoke = client.patch(
            "/admin/docs/acme:hr-salary/acl",
            headers=admin,
            json={
                "allowed_roles": ["admin"],
                "allowed_users": [],
                "classification": "confidential",
            },
        )
        assert revoke.status_code == 200
        after = client.post("/ask", headers=hr, json=question)
        assert after.status_code == 200 and "ACME-SALARY-7731" not in after.json()["answer"]
        assert "acme:hr-salary" not in {c["doc_id"] for c in after.json()["chunks"]}
        assert client.post("/ask", json=question).status_code == 401

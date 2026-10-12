"""End-to-end public corpus retrieval and HTTP response contracts."""

from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from app.auth import issue_token
from app.config import ROOT, Settings
from app.contracts import Chunk, CurrentUser
from app.corpus_state import CorpusState
from app.ingest import ingest_folder
from app.main import app
from app.rag import RAGEngine, parse_citations, rag_pipeline
from app.vectorstore import create_client, ensure_collection


def test_public_pipeline_shape_and_retrieval():
    result = rag_pipeline("How long is the EU refund window?", Settings().large_model)
    assert set(result) == {
        "answer",
        "sources",
        "chunks",
        "model",
        "in_tokens",
        "out_tokens",
        "latency_ms",
    }
    assert len(result["chunks"]) == 5
    assert "refunds-eu.md" in {chunk["source"] for chunk in result["chunks"]}
    assert all(
        set(chunk) == {"id", "score", "text", "source", "doc_id"} for chunk in result["chunks"]
    )
    assert result["sources"]
    assert result["in_tokens"] > 0 and result["out_tokens"] > 0


def test_ask_response_and_unknown_fields():
    with TestClient(app) as client:
        response = client.post(
            "/ask",
            json={"question": "How many seats are included on Pro?", "tenant_id": "spoof"},
            headers={
                "Authorization": "Bearer "
                + issue_token(CurrentUser("acme.admin", "acme", ("employee", "admin")))
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["chunks"]) == 5
        assert data["answer"] and data["model"] == Settings().large_model
        assert "tenant_id" not in data
        assert client.get("/health").status_code == 200


@pytest.mark.parametrize(
    "body", [{}, {"question": ""}, {"question": " \n "}, {"question": "x" * 8001}, {"question": 42}]
)
def test_ask_rejects_invalid_questions(body):
    with TestClient(app) as client:
        headers = {
            "Authorization": "Bearer "
            + issue_token(CurrentUser("acme.admin", "acme", ("employee", "admin")))
        }
        assert client.post("/ask", json=body, headers=headers).status_code == 422


def test_empty_collection_abstains():
    with closing(create_client()) as client:
        ensure_collection(client, "baseline_chunks")
        result = RAGEngine(client).answer("What is the refund window?", Settings().large_model)
        assert result["answer"] == "I don't know"
        assert result["chunks"] == result["sources"] == []


def test_context_prompt_and_citation_parsing(monkeypatch):
    from app import rag
    from app.llm import LLMResult

    observed = {}

    def completion(prompt, model, system=None):
        observed.update(prompt=prompt, system=system)
        return LLMResult(
            "A finding [2] and another [1], repeat [2], bad [99] [0].", 20, 10, model, 0
        )

    monkeypatch.setattr(rag, "complete", completion)
    with closing(create_client()) as client:
        ingest_folder(ROOT / "data" / "docs_sample", client, CorpusState(Settings().state_db))
        result = RAGEngine(client).answer("What are the plans?", Settings().large_model)
    assert observed["prompt"].startswith("Context:\n[1]")
    assert "[5]" in observed["prompt"] and "Question: What are the plans?" in observed["prompt"]
    assert "only from" in observed["system"] and "I don't know" in observed["system"]
    assert result["sources"] == [
        result["chunks"][1]["source"],
        result["chunks"][0]["source"],
    ]


def test_citations_deduplicate_same_source():
    chunks = [
        Chunk(id=str(i), score=1, text="text", source="shared.md", doc_id="doc") for i in range(2)
    ]
    assert parse_citations("[2] [1] [22] [0]", chunks) == ["shared.md"]


def test_baseline_rejects_acl_evidence():
    with closing(create_client()) as client:
        ensure_collection(client, "baseline_chunks")
        from qdrant_client import models

        from app.embed import embed

        client.upsert(
            "baseline_chunks",
            [
                models.PointStruct(
                    id=1, vector=embed(["secret"])[0].tolist(), payload={"tenant_id": "acme"}
                )
            ],
        )
        with pytest.raises(PermissionError):
            RAGEngine(client).answer("secret", Settings().large_model)

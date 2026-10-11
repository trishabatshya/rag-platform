"""Offline contracts for the shared adapters and portable runner."""

from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi.testclient import TestClient
from qdrant_client import models

import tasks
from app.embed import embed
from app.llm import LLMResult, complete
from app.main import app
from app.vectorstore import create_client, ensure_collection
from tasks import COMMANDS


@pytest.fixture(autouse=True)
def mock_mode(monkeypatch):
    monkeypatch.setenv("RAG_MODE", "mock")


def test_embeddings():
    texts = ["Northwind Cloud pricing", "", "你好", "C:\\Users\\Test User\\docs"]
    vectors = embed(texts)
    assert vectors.shape == (4, 384)
    assert vectors.dtype == np.float32
    np.testing.assert_array_equal(vectors, embed(texts))
    np.testing.assert_allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-6)
    assert embed([]).shape == (0, 384)


def test_completion():
    result = complete("Context:\n[1] Pro costs 19 credits.\nQuestion: Price?", "mock")
    assert isinstance(result, LLMResult)
    assert result.text == "Pro costs 19 credits. [1]"
    assert result.in_tokens > 0 and result.out_tokens > 0
    assert result.latency_ms >= 0


def test_qdrant_memory():
    with closing(create_client()) as client:
        ensure_collection(client)
        ensure_collection(client)
        client.upsert("chunks", [models.PointStruct(id=1, vector=embed(["hello"])[0].tolist())])
        assert client.count("chunks").count == 1
        assert client.query_points("chunks", query=embed(["hello"])[0].tolist()).points[0].id == 1
    with closing(create_client()) as client:
        assert not client.collection_exists("chunks")


def test_runner_targets():
    assert set(COMMANDS) == {
        "install",
        "test",
        "lint",
        "up",
        "down",
        "ingest",
        "run",
        "eval",
        "bench-cache",
        "bench-acl",
        "bench-graph",
        "dashboard",
        "report",
    }


def test_runner_preserves_paths_and_exit_status(monkeypatch, tmp_path):
    work = tmp_path / "Windows path with spaces"
    work.mkdir()
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=17)

    monkeypatch.setattr(tasks, "ROOT", work)
    monkeypatch.setattr(tasks.subprocess, "run", run)
    monkeypatch.setattr(tasks.sys, "argv", ["tasks.py", "test", "-q"])
    assert tasks.main() == 17
    command, kwargs = calls[0]
    assert command[-1] == "-q"
    assert kwargs["cwd"] == Path(work)
    assert kwargs["env"]["RAG_MODE"] == "mock"
    assert "shell" not in kwargs


def test_health():
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok", "mode": "mock"}

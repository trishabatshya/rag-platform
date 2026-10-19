"""Hermetic offline settings and Windows-safe resource cleanup for every test."""

import pytest

from app.rag import close_engine
from app.secure_rag import close_secure_engine
from app.service import close_service
from graphrag.pipeline import close_pipeline


@pytest.fixture(autouse=True)
def offline_settings(monkeypatch, tmp_path):
    """Isolate corpus state and ensure tests never select a network-backed adapter."""
    close_service()
    close_engine()
    close_secure_engine()
    close_pipeline()
    monkeypatch.setenv("RAG_MODE", "mock")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "120")
    monkeypatch.setenv("LLM_MAX_TOKENS", "400")
    monkeypatch.setenv("RAG_STATE_DB", str(tmp_path / "state with spaces.db"))
    monkeypatch.setenv("RAG_AUDIT_DB", str(tmp_path / "audit with spaces.db"))
    monkeypatch.setenv("RAG_REQUESTS_DB", str(tmp_path / "requests with spaces.db"))
    monkeypatch.setenv("GRAPH_EXTRACT_CACHE", str(tmp_path / "graph cache with spaces"))
    monkeypatch.setenv("EXTRACT_FAILURE_LOG", str(tmp_path / "extraction_failures.log"))
    monkeypatch.setenv("ROUTER_MODE", "rule")
    monkeypatch.setenv("RETRIEVAL_MODE", "vector")
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    yield
    close_service()
    close_engine()
    close_secure_engine()
    close_pipeline()

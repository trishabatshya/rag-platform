"""Hermetic offline settings and Windows-safe resource cleanup for every test."""

import pytest

from app.rag import close_engine
from app.secure_rag import close_secure_engine


@pytest.fixture(autouse=True)
def offline_settings(monkeypatch, tmp_path):
    """Isolate corpus state and ensure tests never select a network-backed adapter."""
    close_engine()
    close_secure_engine()
    monkeypatch.setenv("RAG_MODE", "mock")
    monkeypatch.setenv("RAG_STATE_DB", str(tmp_path / "state with spaces.db"))
    monkeypatch.setenv("RAG_AUDIT_DB", str(tmp_path / "audit with spaces.db"))
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    yield
    close_engine()
    close_secure_engine()

"""Same seed-derived leakage cases on LIVE Qdrant, with mock models and SQLite audit.

Opt in with RUN_QDRANT_INTEGRATION=1. The URL is deliberately fixed to localhost;
unavailable services fail rather than silently switching to an in-memory backend.
"""

import os
from contextlib import closing
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.engine import URL

from app.audit import AuditStore
from app.corpus_state import CorpusState
from app.ingest import ingest_acl_documents
from app.secure_rag import SecureRAGEngine
from app.vectorstore import ensure_collection
from tests import test_leakage as leakage_cases
from tests.acl_helpers import ADVERSARIAL_QUERIES, SEED_DOCUMENTS, SEED_USERS, RecordingClient

LIVE_URL = "http://localhost:6333"
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_QDRANT_INTEGRATION") != "1",
        reason="Set RUN_QDRANT_INTEGRATION=1 to test live Qdrant at localhost:6333",
    ),
]


@pytest.fixture(scope="module")
def live_leakage_harness(tmp_path_factory):
    """Own an isolated server collection and local audit; never touch app collections."""
    root = tmp_path_factory.mktemp("Live Qdrant leakage paths")
    collection = "leakage_integration_" + uuid4().hex
    # Module fixtures precede function-scoped offline_settings: force the model mode
    # here too, so ingestion and queries use the same deterministic hash embeddings.
    with (
        pytest.MonkeyPatch.context() as patch,
        closing(RecordingClient(url=LIVE_URL)) as client,
        closing(AuditStore(URL.create("sqlite", database=str(root / "audit.db")))) as audit,
    ):
        patch.setenv("RAG_MODE", "mock")
        assert client.init_options["url"] == LIVE_URL
        state = CorpusState(root / "state.db")
        owned = False
        try:
            # A UUID collision must fail, never grant ownership of someone else's collection.
            assert not client.collection_exists(collection)
            ensure_collection(client, collection)
            owned = True
            ingest_acl_documents(SEED_DOCUMENTS, client, state, collection=collection)
            points, _ = client.scroll(collection, limit=1000)
            mapping = {str(p.id): p.payload["doc_id"] for p in points}
            assert set(mapping.values()) == {d["doc_id"] for d in SEED_DOCUMENTS}
            yield SimpleNamespace(
                engine=SecureRAGEngine(client, state, audit, collection=collection),
                mapping=mapping,
            )
        finally:
            if owned:
                client.delete_collection(collection)


@pytest.mark.parametrize("record", SEED_USERS, ids=[u["user_id"] for u in SEED_USERS])
@pytest.mark.parametrize(
    "question",
    ADVERSARIAL_QUERIES,
    ids=[f"attack-{i:02d}" for i in range(len(ADVERSARIAL_QUERIES))],
)
def test_live_qdrant_zero_forbidden_retrievals_and_answers(live_leakage_harness, record, question):
    """Reuse the exact raw-result/response/positive-access/JWT/audit assertions."""
    leakage_cases.test_zero_forbidden_retrievals_and_answers(live_leakage_harness, record, question)


def test_live_negative_control_detects_disabled_filter(live_leakage_harness, monkeypatch, caplog):
    """A missing prefilter MUST expose a raw leak; the Python post-check still protects output."""
    leakage_cases.test_negative_control_detects_disabled_pre_filter(
        live_leakage_harness, monkeypatch, caplog
    )


def test_live_negative_control_detects_both_defenses_disabled(live_leakage_harness, monkeypatch):
    """The independent response oracle must detect forbidden output if both defenses are off."""
    leakage_cases.test_negative_control_detects_both_defenses_disabled(
        live_leakage_harness, monkeypatch
    )

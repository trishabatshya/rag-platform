"""The independent seed oracle through the cached service, including every repeated hit."""

from contextlib import closing
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

from app.audit import AuditLog, AuditStore
from app.auth import issue_token, verify_token
from app.cache import SemanticCache
from app.contracts import CurrentUser
from app.corpus_state import CorpusState
from app.ingest import ingest_acl_documents
from app.logging_db import RequestStore
from app.secure_rag import SecureRAGEngine
from app.service import RAGService
from tests.acl_helpers import (
    ADVERSARIAL_QUERIES,
    SEED_DOCUMENTS,
    SEED_USERS,
    RecordingClient,
    assert_no_raw_leak,
    assert_no_response_leak,
)


@pytest.fixture(scope="module")
def cached_harness(tmp_path_factory):
    root = tmp_path_factory.mktemp("Cached leakage Windows paths")
    with (
        pytest.MonkeyPatch.context() as patch,
        closing(RecordingClient()) as client,
        closing(AuditStore(URL.create("sqlite", database=str(root / "audit.db")))) as audit,
        closing(RequestStore(URL.create("sqlite", database=str(root / "requests.db")))) as requests,
    ):
        patch.setenv("RAG_MODE", "mock")
        state = CorpusState(root / "state.db")
        ingest_acl_documents(SEED_DOCUMENTS, client, state)
        points, _ = client.scroll("chunks", limit=1000)
        mapping = {str(point.id): point.payload["doc_id"] for point in points}
        engine = SecureRAGEngine(client, state, audit)
        yield SimpleNamespace(
            engine=engine,
            mapping=mapping,
            service=RAGService(engine, SemanticCache(client, state), requests),
        )


@pytest.mark.parametrize("record", SEED_USERS, ids=[user["user_id"] for user in SEED_USERS])
@pytest.mark.parametrize(
    "question",
    ADVERSARIAL_QUERIES,
    ids=[f"attack-{i:02d}" for i in range(len(ADVERSARIAL_QUERIES))],
)
def test_cached_service_never_leaks_tenant_role_or_user_evidence(cached_harness, record, question):
    identity = verify_token(
        issue_token(CurrentUser(record["user_id"], record["tenant_id"], tuple(record["roles"])))
    )
    first = cached_harness.service.ask(question, identity)
    assert_no_raw_leak(cached_harness.engine.client.last_points, identity, cached_harness.mapping)
    assert_no_response_leak(first.response, identity, cached_harness.mapping)
    repeated = cached_harness.service.ask(question, identity)
    assert repeated.cache_hit
    assert_no_raw_leak(cached_harness.engine.client.last_points, identity, cached_harness.mapping)
    assert_no_response_leak(repeated.response, identity, cached_harness.mapping)
    with Session(cached_harness.engine.audit.engine) as session:
        row = session.scalars(
            select(AuditLog).where(AuditLog.request_id == repeated.request_id)
        ).one()
        assert (
            row.cache_hit
            and row.user_id == identity.user_id
            and row.tenant_id == identity.tenant_id
        )

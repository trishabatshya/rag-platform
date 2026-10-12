"""Strict metadata, pre-filter semantics, post-check and immediate multi-chunk revoke."""

import copy
from contextlib import closing

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

from app import acl
from app.audit import AuditLog, AuditStore
from app.auth import issue_token
from app.config import Settings
from app.contracts import CurrentUser
from app.corpus_state import CorpusState
from app.ingest import ingest_acl_documents, ingest_folder
from app.main import app
from app.secure_rag import SecureRAGEngine, get_secure_engine
from app.vectorstore import create_client, ensure_acl_indexes
from tests.acl_helpers import SEED_DOCUMENTS


@pytest.mark.parametrize("field", ["tenant_id", "allowed_roles", "classification", "doc_id"])
def test_acl_ingestion_rejects_missing_metadata_before_writes(field):
    bad = copy.deepcopy(SEED_DOCUMENTS[0])
    del bad[field]
    with closing(create_client()) as client:
        with pytest.raises(ValueError):
            ingest_acl_documents([SEED_DOCUMENTS[1], bad], client, CorpusState(Settings().state_db))
        assert not client.collection_exists("chunks")


@pytest.mark.parametrize(
    "field,value",
    [
        ("allowed_roles", "admin"),
        ("classification", "top-secret"),
        ("tenant_id", ""),
        ("doc_id", "globex:public-faq"),
    ],
)
def test_acl_ingestion_rejects_invalid_metadata(field, value):
    bad = {**SEED_DOCUMENTS[0], field: value}
    with closing(create_client()) as client:
        with pytest.raises(ValueError):
            ingest_acl_documents([bad], client, CorpusState(Settings().state_db))


def test_bare_folder_cannot_write_to_acl_collection(tmp_path):
    (tmp_path / "doc.md").write_text("public", encoding="utf-8")
    with closing(create_client()) as client:
        with pytest.raises(ValueError, match="explicit metadata"):
            ingest_folder(tmp_path, client, CorpusState(Settings().state_db), collection="chunks")


def test_server_payload_index_fields_and_local_guard():
    from types import SimpleNamespace

    calls = []
    server = SimpleNamespace(
        init_options={"location": None, "path": None},
        create_payload_index=lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    ensure_acl_indexes(server)
    assert {arguments[1] for arguments, _ in calls} == {
        "tenant_id",
        "allowed_roles",
        "allowed_users",
        "doc_id",
    }
    with closing(create_client()) as client:
        ensure_acl_indexes(client)


def test_postcheck_rejects_missing_or_malformed_grants():
    user = CurrentUser("acme.employee", "acme", ("employee",))
    assert not acl.can_access({}, user)
    assert not acl.can_access({**SEED_DOCUMENTS[0], "allowed_roles": "employee"}, user)
    assert not acl.can_access(SEED_DOCUMENTS[6], user)


def test_deny_all_and_explicit_user_grants():
    document = next(doc for doc in SEED_DOCUMENTS if doc["doc_id"] == "acme:contractor-note")
    assert acl.can_access(document, CurrentUser("acme.contractor", "acme", ()))
    assert not acl.can_access(document, CurrentUser("acme.admin", "acme", ("admin",)))
    assert not acl.can_access(
        {**document, "allowed_users": []}, CurrentUser("acme.contractor", "acme", ())
    )


def test_revoke_updates_every_chunk_and_next_query_cannot_see_document(tmp_path):
    document = {**SEED_DOCUMENTS[2], "text": " ".join(f"release{i}" for i in range(1000))}
    employee = CurrentUser("acme.engineer", "acme", ("employee", "engineer"))
    admin = CurrentUser("acme.admin", "acme", ("admin",))
    state = CorpusState(Settings().state_db)
    audit = AuditStore(URL.create("sqlite", database=str(tmp_path / "audit.db")))
    with closing(create_client()) as client, closing(audit):
        ingest_acl_documents([document], client, state)
        engine = SecureRAGEngine(client, state, audit)
        before = engine.answer("release50", Settings().large_model, employee)
        assert len(before["chunks"]) == 3
        epoch = state.cache_epoch
        result = acl.update_acl(
            document["doc_id"],
            allowed_roles=["admin"],
            allowed_users=[],
            classification="confidential",
            user=admin,
            client=client,
            state=state,
        )
        assert result == {"updated_chunks": 3, "cache_epoch": epoch + 1}
        assert CorpusState(Settings().state_db).cache_epoch == epoch + 1
        after = engine.answer("release50", Settings().large_model, employee)
        assert after["chunks"] == [] and after["answer"] == "I don't know"
        points, _ = client.scroll("chunks", limit=10)
        assert all(
            point.payload["allowed_roles"] == ["admin"]
            and point.payload["classification"] == "confidential"
            for point in points
        )
        with Session(audit.engine) as session:
            assert session.scalar(select(func.count()).select_from(AuditLog)) == 2
            assert (
                session.scalars(select(AuditLog).order_by(AuditLog.id.desc())).first().chunk_ids
                == []
            )


def test_admin_update_is_tenant_scoped_and_http_revoke_is_immediate():
    with TestClient(app) as client:
        employee = {
            "Authorization": "Bearer "
            + issue_token(CurrentUser("acme.hr", "acme", ("employee", "hr")))
        }
        admin = {
            "Authorization": "Bearer "
            + issue_token(CurrentUser("acme.admin", "acme", ("employee", "admin")))
        }
        changes = {
            "allowed_roles": ["admin"],
            "allowed_users": [],
            "classification": "confidential",
            "tenant_id": "globex",
        }
        before = client.post("/ask", json={"question": "ACME-SALARY-7731"}, headers=employee).json()
        assert "acme:hr-salary" in {chunk["doc_id"] for chunk in before["chunks"]}
        assert (
            client.patch(
                "/admin/docs/acme:hr-salary/acl", json=changes, headers=employee
            ).status_code
            == 403
        )
        state = get_secure_engine().state
        epoch = state.cache_epoch
        assert (
            client.patch(
                "/admin/docs/globex:hr-salary/acl", json=changes, headers=admin
            ).status_code
            == 404
        )
        assert state.cache_epoch == epoch
        assert (
            client.patch("/admin/docs/acme:hr-salary/acl", json=changes, headers=admin).status_code
            == 200
        )
        after = client.post("/ask", json={"question": "ACME-SALARY-7731"}, headers=employee).json()
        assert "acme:hr-salary" not in {chunk["doc_id"] for chunk in after["chunks"]}
        assert "ACME-SALARY-7731" not in after["answer"]


def test_failed_retrieval_is_audited_and_audit_failure_blocks_generation(tmp_path, monkeypatch):
    import app.rag as rag

    state = CorpusState(Settings().state_db)
    audit = AuditStore(URL.create("sqlite", database=str(tmp_path / "audit.db")))
    user = CurrentUser("acme.employee", "acme", ("employee",))
    with closing(create_client()) as client, closing(audit):
        ingest_acl_documents(SEED_DOCUMENTS, client, state)
        engine = SecureRAGEngine(client, state, audit)
        original = client.query_points

        def broken(*args, **kwargs):
            raise RuntimeError("vector store unavailable")

        monkeypatch.setattr(client, "query_points", broken)
        with pytest.raises(RuntimeError, match="vector store"):
            engine.answer("question", Settings().large_model, user)
        with Session(audit.engine) as session:
            assert session.scalars(select(AuditLog)).first().outcome == "error"
        monkeypatch.setattr(client, "query_points", original)

        def bad_audit(*args, **kwargs):
            raise RuntimeError("audit storage unavailable")

        def forbidden(*args, **kwargs):
            raise AssertionError("Generation must be blocked if audit cannot commit")

        monkeypatch.setattr(audit, "append", bad_audit)
        monkeypatch.setattr(rag, "complete", forbidden)
        with pytest.raises(RuntimeError, match="audit storage"):
            engine.answer("question", Settings().large_model, user)

"""Append-only database enforcement and exact tenant/date-scoped access queries."""

from contextlib import closing
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit import AuditDocument, AuditLog, AuditStore, create_audit_store
from app.config import Settings
from app.contracts import CurrentUser


@pytest.mark.parametrize(
    "table,operation",
    [
        ("audit_log", "UPDATE audit_log SET query='changed'"),
        ("audit_log", "DELETE FROM audit_log"),
        ("audit_doc_access", "UPDATE audit_doc_access SET doc_id='changed'"),
        ("audit_doc_access", "DELETE FROM audit_doc_access"),
    ],
)
def test_sqlite_prevents_updates_and_deletes(tmp_path, table, operation):
    with closing(
        AuditStore(URL.create("sqlite", database=str(tmp_path / "Audit Windows path.db")))
    ) as store:
        user = CurrentUser("acme.employee", "acme", ("employee",))
        store.append("request", user, "question", ["chunk"], ["acme:doc"], "mock")
        with pytest.raises(IntegrityError, match="append-only"), store.engine.begin() as connection:
            connection.execute(text(operation))
        with Session(store.engine) as session:
            assert len(list(session.scalars(select(AuditLog)))) == 1
            assert len(list(session.scalars(select(AuditDocument)))) == 1


def test_doc_access_is_exact_tenant_scoped_and_excludes_old_rows(tmp_path):
    admin = CurrentUser("acme.admin", "acme", ("admin",))
    with closing(AuditStore(URL.create("sqlite", database=str(tmp_path / "audit.db")))) as store:
        store.append("first", admin, "question", ["chunk"], ["shared-doc"], "mock")
        store.append("prefix", admin, "question", ["chunk"], ["shared-doc-extra"], "mock")
        store.append(
            "foreign",
            CurrentUser("globex.admin", "globex", ("admin",)),
            "question",
            ["chunk"],
            ["shared-doc"],
            "mock",
        )
        # Insert historical evidence directly; append-only triggers prohibit retroactive edits.
        with Session(store.engine) as session, session.begin():
            old = AuditLog(
                request_id="old",
                ts=datetime.now(UTC) - timedelta(days=40),
                user_id=admin.user_id,
                tenant_id="acme",
                query="old",
                chunk_ids=[],
                doc_ids=["shared-doc"],
                model="mock",
            )
            session.add(old)
            session.flush()
            session.add(AuditDocument(audit_id=old.id, doc_id="shared-doc"))
        assert [row["request_id"] for row in store.doc_access("shared-doc", admin)] == ["first"]
        assert len(store.doc_access("shared-doc", admin, days=60)) == 2
        with pytest.raises(PermissionError):
            store.doc_access("shared-doc", CurrentUser("acme.employee", "acme", ("employee",)))


def test_mock_audit_never_uses_postgres_environment(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://unreachable.invalid/never_connect")
    with closing(create_audit_store()) as store:
        assert store.engine.dialect.name == "sqlite"
        assert store.engine.url.database == str(Settings().audit_db)


def test_sqlite_replace_cannot_bypass_append_only_triggers(tmp_path):
    with closing(AuditStore(URL.create("sqlite", database=str(tmp_path / "audit.db")))) as store:
        identity = CurrentUser("acme.employee", "acme", ("employee",))
        record_id = store.append("first", identity, "original", ["chunk"], ["acme:doc"], "mock")
        for table in ("audit_log", "audit_doc_access"):
            with (
                pytest.raises(IntegrityError, match="append-only"),
                store.engine.begin() as connection,
            ):
                connection.execute(text(f"INSERT OR REPLACE INTO {table} SELECT * FROM {table}"))
        with Session(store.engine) as session:
            assert session.get(AuditLog, record_id).query == "original"

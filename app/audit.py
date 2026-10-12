"""Append-only retrieval audit with SQLAlchemy and exact tenant-scoped document lookup."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    select,
)
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from app.config import ROOT, Settings
from app.contracts import CurrentUser


class Base(DeclarativeBase):
    """Audit schema metadata."""


class AuditLog(Base):
    """Immutable evidence of a retrieval, including empty results and dropped violations."""

    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[str] = mapped_column(String, index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    user_id: Mapped[str] = mapped_column(String)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    query: Mapped[str] = mapped_column(Text)
    chunk_ids: Mapped[list[str]] = mapped_column(JSON)
    doc_ids: Mapped[list[str]] = mapped_column(JSON)
    model: Mapped[str] = mapped_column(String)
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    outcome: Mapped[str] = mapped_column(String, default="ok")
    violation_count: Mapped[int] = mapped_column(Integer, default=0)


class AuditDocument(Base):
    """Immutable exact-match index for document access (avoids JSON substring matching)."""

    __tablename__ = "audit_doc_access"
    audit_id: Mapped[int] = mapped_column(ForeignKey("audit_log.id"), primary_key=True)
    doc_id: Mapped[str] = mapped_column(String, primary_key=True, index=True)


class AuditStore:
    """Append and read audit records; no update/delete API is provided."""

    def __init__(self, url: str | URL) -> None:
        parsed = make_url(url) if isinstance(url, str) else url
        if parsed.get_backend_name() == "sqlite":
            if parsed.database and parsed.database != ":memory:":
                Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)
            self.engine = create_engine(parsed, connect_args={"check_same_thread": False})
        else:
            self.engine = create_engine(parsed, pool_pre_ping=True)
        try:
            Base.metadata.create_all(self.engine)
            with self.engine.begin() as connection:
                if self.engine.dialect.name == "sqlite":
                    for table in ("audit_log", "audit_doc_access"):
                        for operation in ("UPDATE", "DELETE"):
                            connection.exec_driver_sql(
                                f"CREATE TRIGGER IF NOT EXISTS {table}_no_{operation.lower()} "
                                f"BEFORE {operation} ON {table} BEGIN "
                                "SELECT RAISE(ABORT, 'audit is append-only'); END"
                            )
                        keys = ("id",) if table == "audit_log" else ("audit_id", "doc_id")
                        same_identity = " AND ".join(f"{key}=NEW.{key}" for key in keys)
                        # SQLite REPLACE can bypass DELETE triggers unless recursive triggers
                        # are enabled. Reject an existing identity before its replacement.
                        connection.exec_driver_sql(
                            f"CREATE TRIGGER IF NOT EXISTS {table}_no_replace "
                            f"BEFORE INSERT ON {table} WHEN EXISTS "
                            f"(SELECT 1 FROM {table} WHERE {same_identity}) BEGIN "
                            "SELECT RAISE(ABORT, 'audit is append-only'); END"
                        )
                elif self.engine.dialect.name == "postgresql":
                    migration = (ROOT / "migrations" / "001_append_only_audit.sql").read_text(
                        encoding="utf-8"
                    )
                    for statement in migration.split("-- STATEMENT"):
                        connection.exec_driver_sql(statement.strip())
                else:
                    raise ValueError("Audit storage supports only SQLite and PostgreSQL")
        except Exception:
            self.engine.dispose()
            raise

    def append(
        self,
        request_id: str,
        user: CurrentUser,
        query: str,
        chunk_ids: list[str],
        doc_ids: list[str],
        model: str,
        *,
        cache_hit: bool = False,
        outcome: str = "ok",
        violation_count: int = 0,
    ) -> int:
        """Commit one retrieval record and its exact document index atomically."""
        with Session(self.engine) as session, session.begin():
            record = AuditLog(
                request_id=request_id,
                ts=datetime.now(UTC),
                user_id=user.user_id,
                tenant_id=user.tenant_id,
                query=query,
                chunk_ids=chunk_ids,
                doc_ids=list(dict.fromkeys(doc_ids)),
                model=model,
                cache_hit=cache_hit,
                outcome=outcome,
                violation_count=violation_count,
            )
            session.add(record)
            session.flush()
            session.add_all(AuditDocument(audit_id=record.id, doc_id=doc) for doc in record.doc_ids)
            return record.id

    def doc_access(self, doc_id: str, user: CurrentUser, days: int = 30) -> list[dict]:
        """Return exact document access records for admins of the same tenant only."""
        if "admin" not in user.roles:
            raise PermissionError("Administrator role required")
        if not 1 <= days <= 365:
            raise ValueError("days must be between 1 and 365")
        cutoff = datetime.now(UTC) - timedelta(days=days)
        query = (
            select(AuditLog)
            .join(AuditDocument)
            .where(
                AuditDocument.doc_id == doc_id,
                AuditLog.tenant_id == user.tenant_id,
                AuditLog.ts >= cutoff,
            )
            .order_by(AuditLog.id.desc())
        )
        with Session(self.engine) as session:
            return [self._serialize(row) for row in session.scalars(query)]

    @staticmethod
    def _serialize(row: AuditLog) -> dict:
        return {
            "id": row.id,
            "request_id": row.request_id,
            "ts": row.ts.replace(tzinfo=UTC).isoformat()
            if row.ts.tzinfo is None
            else row.ts.isoformat(),
            "user_id": row.user_id,
            "tenant_id": row.tenant_id,
            "query": row.query,
            "chunk_ids": row.chunk_ids,
            "doc_ids": row.doc_ids,
            "model": row.model,
            "cache_hit": row.cache_hit,
            "outcome": row.outcome,
            "violation_count": row.violation_count,
        }

    def close(self) -> None:
        """Dispose all database connections, including Windows file handles."""
        self.engine.dispose()


def create_audit_store() -> AuditStore:
    """Select SQLite unconditionally in mock mode, PostgreSQL in real mode."""
    settings = Settings()
    if settings.mode == "mock":
        return AuditStore(URL.create("sqlite", database=str(settings.audit_db)))
    if make_url(settings.database_url).get_backend_name() != "postgresql":
        raise ValueError("Real-mode audit requires a PostgreSQL DATABASE_URL")
    return AuditStore(settings.database_url)

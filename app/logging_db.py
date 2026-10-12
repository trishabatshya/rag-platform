"""Request instrumentation and estimated reference-price accounting."""

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    create_engine,
    select,
    update,
)
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from app.config import Settings, compute_cost

__all__ = ["RequestEvent", "RequestStore", "compute_cost", "create_request_store"]


class Base(DeclarativeBase):
    """Request log schema metadata, separate from immutable retrieval audit."""


class RequestLog(Base):
    """Per-request measurements; absent quality means no reference judge was run."""

    __tablename__ = "requests"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    query: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String)
    route: Mapped[str] = mapped_column(String)
    cache_hit: Mapped[bool] = mapped_column(Boolean)
    escalated: Mapped[bool] = mapped_column(Boolean)
    in_tok: Mapped[int] = mapped_column(Integer)
    out_tok: Mapped[int] = mapped_column(Integer)
    cost: Mapped[float] = mapped_column(Float)
    latency_ms: Mapped[float] = mapped_column(Float)
    quality: Mapped[float | None] = mapped_column(Float, nullable=True)
    run_tag: Mapped[str] = mapped_column(String, index=True)
    mode: Mapped[str] = mapped_column(String)
    error: Mapped[str | None] = mapped_column(String, nullable=True)


@dataclass(frozen=True)
class RequestEvent:
    """Measured usage from all generation/router calls; cache hits have zero new tokens."""

    id: str
    tenant_id: str
    query: str
    model: str
    route: str
    cache_hit: bool
    escalated: bool
    in_tok: int
    out_tok: int
    cost: float
    latency_ms: float
    run_tag: str
    mode: str
    quality: float | None = None
    error: str | None = None


class RequestStore:
    """Record request events and attach genuinely measured benchmark quality."""

    def __init__(self, url: str | URL) -> None:
        if isinstance(url, URL) and url.get_backend_name() == "sqlite":
            if url.database and url.database != ":memory:":
                Path(url.database).parent.mkdir(parents=True, exist_ok=True)
            self.engine = create_engine(url, connect_args={"check_same_thread": False})
        else:
            self.engine = create_engine(url, pool_pre_ping=True)
        try:
            Base.metadata.create_all(self.engine)
        except Exception:
            self.engine.dispose()
            raise

    def record(self, event: RequestEvent) -> None:
        """Commit observed request usage; do not invent a quality value for API calls."""
        with Session(self.engine) as session, session.begin():
            session.add(RequestLog(ts=datetime.now(UTC), **asdict(event)))

    def set_quality(self, request_id: str, quality: float) -> None:
        """Attach a benchmark judge result to one known request."""
        if not 0 <= quality <= 1:
            raise ValueError("Quality must be in [0,1]")
        with Session(self.engine) as session, session.begin():
            result = session.execute(
                update(RequestLog).where(RequestLog.id == request_id).values(quality=quality)
            )
            if result.rowcount != 1:
                raise LookupError("Request not found")

    def rows(self, run_tag: str | None = None) -> list[dict]:
        """Read measured requests for the local operator dashboard."""
        query = select(RequestLog).order_by(RequestLog.ts)
        if run_tag is not None:
            query = query.where(RequestLog.run_tag == run_tag)
        with Session(self.engine) as session:
            return [
                {column.name: getattr(row, column.name) for column in RequestLog.__table__.columns}
                for row in session.scalars(query)
            ]

    def close(self) -> None:
        """Dispose the request database engine and release Windows file handles."""
        self.engine.dispose()


def create_request_store() -> RequestStore:
    """Use a local SQLite request log in mock mode or configured PostgreSQL in real mode."""
    settings = Settings()
    if settings.mode == "mock":
        return RequestStore(URL.create("sqlite", database=str(settings.requests_db)))
    if make_url(settings.database_url).get_backend_name() != "postgresql":
        raise ValueError("Real-mode request logging requires PostgreSQL")
    return RequestStore(settings.database_url)

"""Authenticated tenant retrieval: pre-filter, post-check, audit, then generation."""

import json
import logging
from collections import Counter
from functools import lru_cache
from time import perf_counter
from uuid import uuid4

from qdrant_client import QdrantClient

from app import acl
from app.audit import AuditStore, create_audit_store
from app.config import Settings
from app.contracts import Chunk, CurrentUser, RAGResult
from app.corpus_state import CorpusState
from app.embed import embed
from app.ingest import ingest_acl_documents
from app.rag import generate_answer
from app.vectorstore import create_client, ensure_acl_indexes, ensure_collection


class SecureRAGEngine:
    """Single-worker tenant engine with serialized ACL updates and retrieval snapshots."""

    def __init__(self, client: QdrantClient, state: CorpusState, audit: AuditStore) -> None:
        self.client, self.state, self.audit = client, state, audit
        self._violations: Counter[str] = Counter()

    def retrieve(self, question: str, user: CurrentUser, model: str) -> list[Chunk]:
        """Filter inside query_points, drop violations, and audit even empty/failed retrievals."""
        request_id = str(uuid4())
        with self.state.access_lock:
            violations = 0
            try:
                points = self.client.query_points(
                    "chunks",
                    query=embed([question])[0].tolist(),
                    query_filter=acl.build_filter(user),
                    limit=5,
                    with_payload=True,
                ).points
                chunks = []
                for point in points:
                    payload = point.payload or {}
                    if not acl.can_access(payload, user):
                        violations += 1
                        logging.critical(
                            "ACL post-check violation request=%s user=%s chunk=%s",
                            request_id,
                            user.user_id,
                            point.id,
                        )
                        continue
                    chunks.append(
                        Chunk(
                            id=str(point.id),
                            score=float(point.score),
                            text=payload["text"],
                            source=payload["source"],
                            doc_id=payload["doc_id"],
                        )
                    )
            except Exception:
                self.audit.append(request_id, user, question, [], [], model, outcome="error")
                raise
            self._violations[user.tenant_id] += violations
            self.audit.append(
                request_id,
                user,
                question,
                [chunk["id"] for chunk in chunks],
                [chunk["doc_id"] for chunk in chunks],
                model,
                outcome="postcheck_drop" if violations else "ok",
                violation_count=violations,
            )
            return chunks

    def answer(self, question: str, model: str, user: CurrentUser | None = None) -> RAGResult:
        """Generate from a verified caller's evidence, with auditing before any model call."""
        if user is None:
            raise PermissionError("Verified identity required")
        question = question.strip()
        if not question:
            raise ValueError("Question must not be empty")
        start = perf_counter()
        chunks = self.retrieve(question, user, model)
        return generate_answer(question, model, chunks, start)

    def metrics(self, user: CurrentUser) -> dict[str, int]:
        """Return only the verified tenant's process-local security counter."""
        if "admin" not in user.roles:
            raise PermissionError("Administrator role required")
        with self.state.access_lock:
            return {"acl_postcheck_drops": self._violations[user.tenant_id]}

    def close(self) -> None:
        """Close vector and audit resources."""
        self.client.close()
        self.audit.close()


@lru_cache(maxsize=1)
def get_secure_engine() -> SecureRAGEngine:
    """Create the ACL collection; mock reloads committed tenant fixtures on first use."""
    settings = Settings()
    client = create_client()
    audit = None
    try:
        state = CorpusState(settings.state_db)
        ensure_collection(client, "chunks")
        ensure_acl_indexes(client)
        audit = create_audit_store()
        if settings.mode == "mock":
            documents = json.loads(
                (settings.seed_dir / "documents.json").read_text(encoding="utf-8")
            )
            ingest_acl_documents(documents, client, state)
        return SecureRAGEngine(client, state, audit)
    except Exception:
        client.close()
        if audit is not None:
            audit.close()
        raise


def close_secure_engine() -> None:
    """Release a cached secure engine without creating one during shutdown."""
    if get_secure_engine.cache_info().currsize:
        get_secure_engine().close()
        get_secure_engine.cache_clear()

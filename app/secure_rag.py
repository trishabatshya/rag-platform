"""Authenticated tenant retrieval: pre-filter, post-check, audit, then generation."""

import json
import logging
from collections import Counter
from collections.abc import Callable
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

    def __init__(
        self,
        client: QdrantClient,
        state: CorpusState,
        audit: AuditStore,
        collection: str = "chunks",
    ) -> None:
        self.client, self.state, self.audit = client, state, audit
        self._violations: Counter[str] = Counter()
        self.collection = collection

    def retrieve(
        self,
        question: str,
        user: CurrentUser,
        model: str | Callable[[list[Chunk]], str],
        *,
        vector: list[float] | None = None,
        request_id: str | None = None,
    ) -> list[Chunk]:
        """Filter inside query_points, drop violations, and audit even empty/failed retrievals."""
        request_id = request_id or str(uuid4())
        with self.state.access_lock:
            violations = 0
            try:
                points = self.client.query_points(
                    self.collection,
                    query=vector if vector is not None else embed([question])[0].tolist(),
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
                selected_model = model(chunks) if callable(model) else model
            except Exception:
                self.audit.append(
                    request_id,
                    user,
                    question,
                    [],
                    [],
                    model if isinstance(model, str) else "routing_pending",
                    outcome="error",
                )
                raise
            self._violations[user.tenant_id] += violations
            self.audit.append(
                request_id,
                user,
                question,
                [chunk["id"] for chunk in chunks],
                [chunk["doc_id"] for chunk in chunks],
                selected_model,
                outcome="postcheck_drop" if violations else "ok",
                violation_count=violations,
            )
            return chunks

    def validate_cached_evidence(
        self,
        question: str,
        user: CurrentUser,
        response: RAGResult,
        vector: list[float],
        request_id: str,
    ) -> bool:
        """Pre-filter exact evidence IDs, recheck metadata/text, and audit cached delivery."""
        from qdrant_client import models

        with self.state.access_lock:
            original = response["chunks"]
            try:
                points = self.client.query_points(
                    self.collection,
                    query=vector,
                    limit=max(1, len(original)),
                    with_payload=True,
                    query_filter=models.Filter(
                        must=[
                            acl.build_filter(user),
                            models.HasIdCondition(has_id=[chunk["id"] for chunk in original]),
                        ]
                    ),
                ).points
            except Exception:
                self.audit.append(
                    request_id, user, question, [], [], response["model"], outcome="error"
                )
                raise
            by_id = {str(point.id): point.payload or {} for point in points}
            violations = sum(not acl.can_access(payload, user) for payload in by_id.values())
            if violations:
                logging.critical(
                    "ACL cache post-check violation request=%s user=%s", request_id, user.user_id
                )
                self._violations[user.tenant_id] += violations
            valid = (
                bool(original)
                and not violations
                and len(by_id) == len(original)
                and all(
                    by_id.get(chunk["id"], {}).get("text") == chunk["text"]
                    and by_id.get(chunk["id"], {}).get("doc_id") == chunk["doc_id"]
                    and by_id.get(chunk["id"], {}).get("source") == chunk["source"]
                    for chunk in original
                )
            )
            self.audit.append(
                request_id,
                user,
                question,
                [chunk["id"] for chunk in original] if valid else [],
                [chunk["doc_id"] for chunk in original] if valid else [],
                response["model"],
                cache_hit=valid,
                outcome="ok" if valid else "cache_rejected",
                violation_count=violations,
            )
            return valid

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

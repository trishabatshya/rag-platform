"""Semantic cache with tenant, role, explicit-user, version, epoch and TTL isolation."""

import copy
import hashlib
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5

from qdrant_client import QdrantClient, models

from app.config import Settings
from app.contracts import CurrentUser, RAGResult
from app.corpus_state import CorpusState
from app.embed import embed
from app.vectorstore import ensure_collection

QUESTION_WORDS = {
    "how",
    "what",
    "which",
    "when",
    "where",
    "who",
    "why",
    "is",
    "are",
    "can",
    "does",
    "do",
    "show",
    "tell",
    "give",
    "please",
    "explain",
    "compare",
    "after",
    "within",
    "for",
    "at",
}


def normalize_query(question: str) -> str:
    """Case-fold and replace punctuation with spaces before embedding."""
    return " ".join(re.sub(r"[^\w\s]", " ", question.casefold()).split())


def roles_fingerprint(user: CurrentUser) -> str:
    """Hash sorted, unique roles, independent of their order in a verified JWT."""
    return hashlib.sha256(json.dumps(sorted(set(user.roles))).encode()).hexdigest()


def guard_signature(question: str) -> tuple[set[str], set[str]]:
    """Extract numbers and capitalized entity-like tokens, excluding question openers."""
    numbers = set(re.findall(r"\b\d+(?:\.\d+)?\b", question))
    entities = {
        token.casefold()
        for token in re.findall(r"\b[A-Z][A-Za-z0-9_-]*\b", question)
        if token.casefold() not in QUESTION_WORDS
    }
    return numbers, entities


def entity_number_guard(first: str, second: str) -> bool:
    """Reject a semantic hit when its number or entity token sets differ."""
    return guard_signature(first) == guard_signature(second)


@dataclass(frozen=True)
class CacheHit:
    """Cached answer plus the snapshot that must still match when it is served."""

    response: RAGResult
    score: float
    version: int
    epoch: int


class SemanticCache:
    """Nearest-neighbor answer cache; callers must pass a verified identity."""

    def __init__(
        self,
        client: QdrantClient,
        state: CorpusState,
        *,
        collection: str = "cache",
        threshold: float | None = None,
        ttl: float | None = None,
        guard: bool | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        settings = Settings()
        self.client, self.state, self.collection = client, state, collection
        self.threshold = settings.cache_threshold if threshold is None else threshold
        self.ttl = settings.cache_ttl if ttl is None else ttl
        self.guard = settings.cache_guard if guard is None else guard
        self.clock = clock
        if not 0 <= self.threshold <= 1 or self.ttl <= 0:
            raise ValueError("Require threshold in [0,1] and positive TTL")
        ensure_collection(client, collection)

    def lookup(
        self, question: str, user: CurrentUser | None, vector: list[float] | None = None
    ) -> CacheHit | None:
        """Pre-filter by identity/snapshot/age; never search the cache anonymously."""
        if user is None:
            return None
        with self.state.access_lock:
            version, epoch, now = self.state.version, self.state.cache_epoch, self.clock()
            criteria = models.Filter(
                must=[
                    models.FieldCondition(
                        key="tenant_id", match=models.MatchValue(value=user.tenant_id)
                    ),
                    models.FieldCondition(
                        key="roles_fingerprint",
                        match=models.MatchValue(value=roles_fingerprint(user)),
                    ),
                    # Roles alone cannot isolate explicit-user-only document grants.
                    models.FieldCondition(
                        key="user_id", match=models.MatchValue(value=user.user_id)
                    ),
                    models.FieldCondition(key="version", match=models.MatchValue(value=version)),
                    models.FieldCondition(key="epoch", match=models.MatchValue(value=epoch)),
                    models.FieldCondition(key="ts", range=models.Range(gt=now - self.ttl, lte=now)),
                ]
            )
            points = self.client.query_points(
                self.collection,
                query=vector or embed([normalize_query(question)])[0].tolist(),
                query_filter=criteria,
                score_threshold=self.threshold,
                limit=10,
                with_payload=True,
            ).points
            for point in points:
                if float(point.score) < self.threshold:
                    continue
                payload = point.payload or {}
                if (
                    payload.get("tenant_id") != user.tenant_id
                    or payload.get("roles_fingerprint") != roles_fingerprint(user)
                    or payload.get("user_id") != user.user_id
                ):
                    continue
                if (
                    payload.get("version") != version
                    or payload.get("epoch") != epoch
                    or not 0 <= now - payload.get("ts", 0) < self.ttl
                ):
                    continue
                if self.guard and not entity_number_guard(
                    question, payload.get("original_query", "")
                ):
                    continue
                response = copy.deepcopy(payload["response"])
                response["in_tokens"] = response["out_tokens"] = 0
                return CacheHit(response, float(point.score), version, epoch)
        return None

    def store(
        self,
        question: str,
        response: RAGResult,
        user: CurrentUser | None,
        *,
        version: int,
        epoch: int,
        vector: list[float] | None = None,
    ) -> bool:
        """Store only complete, cited answers from an unchanged permission/corpus snapshot."""
        answer = response["answer"].strip()
        if (
            user is None
            or not answer
            or re.search(r"\bi don['’]t know\b", answer, re.I)
            or not response["sources"]
            or not response["chunks"]
        ):
            return False
        with self.state.access_lock:
            if (version, epoch) != (self.state.version, self.state.cache_epoch):
                return False
            query = normalize_query(question)
            identity = f"{user.tenant_id}/{user.user_id}/{roles_fingerprint(user)}/{query}"
            payload = {
                "query": query,
                "original_query": question,
                "answer": answer,
                "sources": response["sources"],
                "response": dict(response),
                "version": version,
                "epoch": epoch,
                "ts": self.clock(),
                "tenant_id": user.tenant_id,
                "roles_fingerprint": roles_fingerprint(user),
                "user_id": user.user_id,
            }
            self.client.upsert(
                self.collection,
                [
                    models.PointStruct(
                        id=str(uuid5(NAMESPACE_URL, identity)),
                        vector=vector or embed([query])[0].tolist(),
                        payload=payload,
                    )
                ],
                wait=True,
            )
            return True

    def clear(self) -> None:
        """Clear this cache collection without changing its vector schema."""
        with self.state.access_lock:
            self.client.delete(self.collection, points_selector=models.Filter(), wait=True)

    def discard(self, question: str, user: CurrentUser) -> None:
        """Remove an entry if final request instrumentation fails after a cache write."""
        identity = (
            f"{user.tenant_id}/{user.user_id}/{roles_fingerprint(user)}/{normalize_query(question)}"
        )
        self.client.delete(
            self.collection, points_selector=[str(uuid5(NAMESPACE_URL, identity))], wait=True
        )

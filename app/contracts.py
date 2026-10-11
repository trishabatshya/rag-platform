"""Stable types shared by RAG, identity and service implementations."""

from dataclasses import dataclass
from typing import Protocol

from typing_extensions import TypedDict


@dataclass(frozen=True)
class CurrentUser:
    """Verified identity; authentication populates this value in milestone M2."""

    user_id: str
    tenant_id: str
    roles: tuple[str, ...]


class Chunk(TypedDict):
    """Retrieved evidence with its provenance."""

    id: str
    score: float
    text: str
    source: str
    doc_id: str


class RAGResult(TypedDict):
    """Stable response shape for retrieval pipelines."""

    answer: str
    sources: list[str]
    chunks: list[Chunk]
    model: str
    in_tokens: int
    out_tokens: int
    latency_ms: float


class RAGPipeline(Protocol):
    """Callable contract implemented by the baseline and graph pipelines."""

    def __call__(self, question: str, model: str, user: CurrentUser | None = None) -> RAGResult:
        """Answer a question using authorized evidence."""
        ...

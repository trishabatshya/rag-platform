"""HTTP entry point for public-corpus baseline RAG."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.config import Settings
from app.contracts import RAGResult
from app.rag import RAGEngine, close_engine, get_engine


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Release process-local vector resources when the service shuts down."""
    try:
        yield
    finally:
        close_engine()


app = FastAPI(title="Northwind RAG", lifespan=lifespan)


class AskRequest(BaseModel):
    """Baseline request: question only; unknown fields cannot set identity."""

    model_config = ConfigDict(extra="ignore")
    question: str = Field(min_length=1, max_length=8000)

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        """Reject whitespace-only questions before invoking retrieval."""
        if not value.strip():
            raise ValueError("Question must not be empty")
        return value.strip()


@app.post("/ask")
def ask(body: AskRequest, engine: Annotated[RAGEngine, Depends(get_engine)]) -> RAGResult:
    """Answer a public-corpus question with numbered citations."""
    return engine.answer(body.question, Settings().large_model)


@app.get("/health")
def health() -> dict[str, str]:
    """Report service health and the active runtime mode."""
    return {"status": "ok", "mode": Settings().mode}

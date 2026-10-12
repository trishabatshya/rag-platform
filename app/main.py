"""JWT-authenticated HTTP entry point for permission-aware tenant RAG."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.access_models import Classification
from app.acl import update_acl
from app.auth import demo_login, get_current_user, require_admin
from app.config import Settings
from app.contracts import CurrentUser, RAGResult
from app.rag import close_engine
from app.secure_rag import SecureRAGEngine, close_secure_engine, get_secure_engine


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Release process-local vector resources when the service shuts down."""
    try:
        yield
    finally:
        close_engine()
        close_secure_engine()


app = FastAPI(title="Northwind RAG", lifespan=lifespan)


class AskRequest(BaseModel):
    """Question-only request; unknown fields cannot set identity."""

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
def ask(
    body: AskRequest,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    engine: Annotated[SecureRAGEngine, Depends(get_secure_engine)],
) -> RAGResult:
    """Answer using only the caller's verified JWT tenant and role/user grants."""
    return engine.answer(body.question, Settings().large_model, user)


class LoginRequest(BaseModel):
    """Demo-only credentials; tenant and role claims cannot be supplied by a client."""

    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=1024)


@app.post("/auth/login")
def login(body: LoginRequest) -> dict[str, str | int]:
    """Issue a JWT for committed demo users with PBKDF2-hashed passwords."""
    return {
        "access_token": demo_login(body.username, body.password),
        "token_type": "bearer",
        "expires_in": Settings().jwt_ttl_seconds,
    }


class ACLUpdate(BaseModel):
    """Complete replacement of role/user grants and the classification label."""

    allowed_roles: list[str]
    allowed_users: list[str]
    classification: Classification


@app.patch("/admin/docs/{doc_id}/acl")
def change_acl(
    doc_id: str,
    body: ACLUpdate,
    user: Annotated[CurrentUser, Depends(require_admin)],
    engine: Annotated[SecureRAGEngine, Depends(get_secure_engine)],
) -> dict[str, int]:
    """Update every matching chunk in the admin's tenant and invalidate cached evidence."""
    try:
        return update_acl(
            doc_id, **body.model_dump(), user=user, client=engine.client, state=engine.state
        )
    except LookupError as error:
        raise HTTPException(status_code=404, detail="Document not found") from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail="Invalid ACL metadata") from error


@app.get("/admin/doc-access/{doc_id}")
def doc_access(
    doc_id: str,
    user: Annotated[CurrentUser, Depends(require_admin)],
    engine: Annotated[SecureRAGEngine, Depends(get_secure_engine)],
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> list[dict]:
    """List exact document audit records in the verified admin's tenant only."""
    return engine.audit.doc_access(doc_id, user, days)


@app.get("/admin/metrics")
def metrics(
    user: Annotated[CurrentUser, Depends(require_admin)],
    engine: Annotated[SecureRAGEngine, Depends(get_secure_engine)],
) -> dict[str, int]:
    """Expose the tenant's post-filter violation counter to its administrators."""
    return engine.metrics(user)


@app.get("/health")
def health() -> dict[str, str]:
    """Report service health and the active runtime mode."""
    return {"status": "ok", "mode": Settings().mode}

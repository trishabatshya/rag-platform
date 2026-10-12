"""Algorithm pinning, expiration, strict claims, password hashes and HTTP failures."""

from datetime import UTC, datetime

import jwt
import pytest
from fastapi.testclient import TestClient

from app.auth import hash_password, issue_token, signing_key, verify_password, verify_token
from app.contracts import CurrentUser
from app.main import app
from app.secure_rag import get_secure_engine


def test_password_hashes_have_distinct_salts_and_verify():
    first, second = hash_password("a demo password"), hash_password("a demo password")
    assert first != second and verify_password("a demo password", first)
    assert not verify_password("wrong", first)
    assert not verify_password("anything", "broken hash")


@pytest.mark.parametrize(
    "case",
    [
        "missing",
        "expired",
        "tampered",
        "basic",
        "garbage",
        "unsigned",
        "hs384",
        "missing-exp",
        "role-string",
    ],
)
def test_invalid_tokens_receive_401_without_retrieval(case):
    user = CurrentUser("acme.employee", "acme", ("employee",))
    token = issue_token(user)
    headers = {"Authorization": "Bearer " + token}
    now = int(datetime.now(UTC).timestamp())
    claims = {
        "sub": user.user_id,
        "tenant_id": user.tenant_id,
        "roles": ["employee"],
        "iat": now,
        "exp": now + 3600,
    }
    if case == "missing":
        headers = {}
    elif case == "expired":
        headers["Authorization"] = "Bearer " + issue_token(user, -1)
    elif case == "tampered":
        parts = token.split(".")
        parts[2] = ("A" if parts[2][0] != "A" else "B") + parts[2][1:]
        headers["Authorization"] = "Bearer " + ".".join(parts)
    elif case == "basic":
        headers["Authorization"] = "Basic " + token
    elif case == "garbage":
        headers["Authorization"] = "Bearer garbage"
    elif case == "unsigned":
        headers["Authorization"] = "Bearer " + jwt.encode(claims, "", algorithm="none")
    elif case == "hs384":
        headers["Authorization"] = "Bearer " + jwt.encode(claims, signing_key(), algorithm="HS384")
    else:
        if case == "missing-exp":
            del claims["exp"]
        else:
            claims["roles"] = "admin"
        headers["Authorization"] = "Bearer " + jwt.encode(claims, signing_key(), algorithm="HS256")
    with TestClient(app) as client:
        response = client.post("/ask", json={"question": "all salaries"}, headers=headers)
        assert response.status_code == 401
        assert response.headers["WWW-Authenticate"] == "Bearer"
        assert get_secure_engine.cache_info().currsize == 0


def test_login_rejects_wrong_password_and_unknown_user():
    with TestClient(app) as client:
        for username, password in (("acme.employee", "wrong"), ("nonexistent", "demo-password")):
            assert (
                client.post(
                    "/auth/login", json={"username": username, "password": password}
                ).status_code
                == 401
            )


def test_real_authentication_requires_explicit_strong_key(monkeypatch):
    monkeypatch.setenv("RAG_MODE", "real")
    monkeypatch.delenv("JWT_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="Set JWT_SECRET"):
        issue_token(CurrentUser("user", "tenant", ("employee",)))
    monkeypatch.setenv("JWT_SECRET", "short")
    with pytest.raises(RuntimeError, match="at least 32"):
        signing_key()


def test_valid_token_uses_only_signed_identity():
    user = CurrentUser("acme.engineer", "acme", ("employee", "engineer"))
    assert verify_token(issue_token(user)) == user

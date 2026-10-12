"""Demo-only PBKDF2 login and strict HS256 JWT identity verification."""

import hashlib
import hmac
import json
import secrets
from datetime import UTC, datetime
from functools import lru_cache
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.config import Settings
from app.contracts import CurrentUser

PBKDF2_ITERATIONS = 600_000
bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    """Hash a demo password with PBKDF2-SHA256 and an independent random salt."""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    """Verify a password with constant-time digest comparison."""
    try:
        method, count, salt, expected = encoded.split("$")
        if method != "pbkdf2_sha256" or not 100_000 <= int(count) <= 2_000_000:
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(count))
        return hmac.compare_digest(digest, bytes.fromhex(expected))
    except (ValueError, TypeError):
        return False


@lru_cache(maxsize=1)
def _mock_signing_key() -> str:
    return secrets.token_urlsafe(48)


def signing_key() -> str:
    """Use configured key; mock permits a process-local key, real mode fails closed."""
    settings = Settings()
    if settings.jwt_secret:
        if len(settings.jwt_secret.encode()) < 32:
            raise RuntimeError("JWT_SECRET must contain at least 32 bytes")
        return settings.jwt_secret
    if settings.mode == "mock":
        return _mock_signing_key()
    raise RuntimeError("Set JWT_SECRET before running real-mode authentication")


class TokenClaims(BaseModel):
    """Required signed identity claims, checked without coercing types."""

    model_config = ConfigDict(strict=True)
    sub: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    roles: list[str]
    exp: int
    iat: int


def issue_token(user: CurrentUser, ttl_seconds: int | None = None) -> str:
    """Issue a demo login token from a trusted user record, never request-body roles."""
    issued = int(datetime.now(UTC).timestamp())
    ttl = Settings().jwt_ttl_seconds if ttl_seconds is None else ttl_seconds
    return jwt.encode(
        {
            "sub": user.user_id,
            "tenant_id": user.tenant_id,
            "roles": list(user.roles),
            "iat": issued,
            "exp": issued + ttl,
        },
        signing_key(),
        algorithm="HS256",
    )


def verify_token(token: str) -> CurrentUser:
    """Verify signature, expiration, algorithm and claim types before returning identity."""
    decoded = jwt.decode(
        token,
        signing_key(),
        algorithms=["HS256"],
        options={"require": ["sub", "tenant_id", "roles", "exp", "iat"]},
    )
    try:
        claims = TokenClaims.model_validate(decoded)
    except ValidationError as error:
        raise jwt.InvalidTokenError("Malformed identity claims") from error
    if any(not role or role.isspace() for role in claims.roles):
        raise jwt.InvalidTokenError("Malformed role claims")
    return CurrentUser(claims.sub, claims.tenant_id, tuple(claims.roles))


def demo_login(username: str, password: str) -> str:
    """Authenticate committed fictional demo users; no production account management."""
    users = json.loads((Settings().seed_dir / "users.json").read_text(encoding="utf-8"))
    candidate = next((user for user in users if user["user_id"] == username), None)
    # Unknown users perform the same password-work factor as known users.
    record = candidate or users[0]
    valid = verify_password(password, record["password_hash"])
    if candidate is None or not valid:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return issue_token(CurrentUser(record["user_id"], record["tenant_id"], tuple(record["roles"])))


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> CurrentUser:
    """FastAPI identity dependency; missing, expired or tampered tokens receive 401."""
    try:
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise jwt.InvalidTokenError("Bearer token required")
        return verify_token(credentials.credentials)
    except jwt.InvalidTokenError as error:
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from error


def require_admin(user: Annotated[CurrentUser, Depends(get_current_user)]) -> CurrentUser:
    """Authorize tenant administrators from verified JWT roles only."""
    if "admin" not in user.roles:
        raise HTTPException(status_code=403, detail="Administrator role required")
    return user

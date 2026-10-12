"""Tenant pre-filter, independent post-check and tenant-scoped permission changes."""

from qdrant_client import QdrantClient, models

from app.access_models import AccessMetadata, Classification
from app.contracts import CurrentUser
from app.corpus_state import CorpusState


def build_filter(user: CurrentUser) -> models.Filter:
    """Require tenant equality AND at least one role or explicit-user grant in Qdrant."""
    grants: list[models.FieldCondition] = [
        models.FieldCondition(key="allowed_users", match=models.MatchValue(value=user.user_id))
    ]
    if user.roles:
        grants.append(
            models.FieldCondition(key="allowed_roles", match=models.MatchAny(any=list(user.roles)))
        )
    return models.Filter(
        must=[
            models.FieldCondition(key="tenant_id", match=models.MatchValue(value=user.tenant_id))
        ],
        min_should=models.MinShould(conditions=grants, min_count=1),
    )


def can_access(payload: dict, user: CurrentUser) -> bool:
    """Recheck metadata and role/user grants independently after vector retrieval."""
    try:
        metadata = AccessMetadata.model_validate(payload)
    except ValueError:
        return False
    return metadata.tenant_id == user.tenant_id and (
        bool(set(metadata.allowed_roles) & set(user.roles))
        or user.user_id in metadata.allowed_users
    )


def document_filter(doc_id: str, tenant_id: str) -> models.Filter:
    """Scope document mutation and inspection to the verified tenant."""
    return models.Filter(
        must=[
            models.FieldCondition(key="tenant_id", match=models.MatchValue(value=tenant_id)),
            models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id)),
        ]
    )


def update_acl(
    doc_id: str,
    *,
    allowed_roles: list[str],
    allowed_users: list[str],
    classification: Classification,
    user: CurrentUser,
    client: QdrantClient,
    state: CorpusState,
    collection: str = "chunks",
) -> dict[str, int]:
    """Admin-only update of all document chunks, invalidating future cache entries first."""
    if "admin" not in user.roles:
        raise PermissionError("Administrator role required")
    metadata = AccessMetadata(
        tenant_id=user.tenant_id,
        allowed_roles=allowed_roles,
        allowed_users=allowed_users,
        classification=classification,
    )
    selected = document_filter(doc_id, user.tenant_id)
    with state.access_lock:
        count = client.count(collection, count_filter=selected, exact=True).count
        if not count:
            raise LookupError("Document not found")
        # Invalidate before mutation, including failed or partially applied remote writes.
        epoch = state.bump_cache_epoch()
        client.set_payload(collection, metadata.model_dump(), points=selected, wait=True)
    return {"updated_chunks": count, "cache_epoch": epoch}

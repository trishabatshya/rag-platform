"""Qdrant client factory and collection helpers."""

from qdrant_client import QdrantClient, models

from app.config import Settings


def create_client() -> QdrantClient:
    """Create an isolated in-memory client in mock mode, or connect to Qdrant."""
    settings = Settings()
    if settings.mode == "mock":
        return QdrantClient(":memory:")
    return QdrantClient(url=settings.qdrant_url)


def ensure_collection(client: QdrantClient, name: str = "chunks") -> None:
    """Create a cosine collection if it does not already exist."""
    if not client.collection_exists(name):
        client.create_collection(
            name, vectors_config=models.VectorParams(size=384, distance=models.Distance.COSINE)
        )


def ensure_acl_indexes(client: QdrantClient, collection: str = "chunks") -> None:
    """Index ACL query fields on a server; local Qdrant does not support payload indexes."""
    options = client.init_options
    if options.get("location") == ":memory:" or options.get("path") is not None:
        return
    for name in ("tenant_id", "allowed_roles", "allowed_users", "doc_id"):
        client.create_payload_index(collection, name, field_schema=models.PayloadSchemaType.KEYWORD)

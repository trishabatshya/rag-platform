"""Validated trusted-ingestion ACL schema; missing metadata always fails closed."""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Identifier = Annotated[str, Field(min_length=1, pattern=r"^\S+$")]
Classification = Literal["public", "internal", "confidential"]


class AccessMetadata(BaseModel):
    """Explicit role or user grants within one tenant; no classification-based bypass."""

    model_config = ConfigDict(strict=True)
    tenant_id: Identifier
    allowed_roles: list[Identifier]
    allowed_users: list[Identifier] = Field(default_factory=list)
    classification: Classification


class ACLDocument(AccessMetadata):
    """Document whose chunks inherit validated access metadata."""

    doc_id: Identifier
    source: str = Field(min_length=1)
    text: str

    @model_validator(mode="after")
    def tenant_scoped_id(self) -> Self:
        """Require globally distinct tenant-prefixed document IDs."""
        if not self.doc_id.startswith(self.tenant_id + ":"):
            raise ValueError("doc_id must start with tenant_id followed by a colon")
        return self

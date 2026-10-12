"""Small, validated extraction schema; endpoints must reference typed entities."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

EntityType = Literal["PERSON", "ORG", "PLACE", "WORK", "EVENT", "OTHER"]
RelationType = Literal[
    "BORN_IN",
    "DIRECTED",
    "ACTOR_IN",
    "MEMBER_OF",
    "LOCATED_IN",
    "FOUNDED",
    "AUTHORED",
    "PART_OF",
    "RELATED_TO",
]


class Entity(BaseModel):
    """A name and a fixed entity type, never an untyped global identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str = Field(min_length=1)
    type: EntityType

    @model_validator(mode="after")
    def check_name(self) -> "Entity":
        if not self.name.strip():
            raise ValueError("Entity name cannot be blank")
        return self


class Relation(BaseModel):
    """Directed relation whose supporting chunk is supplied by the indexer."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    source: Entity
    type: RelationType
    target: Entity


class Extraction(BaseModel):
    """Strict JSON extraction with no dangling relation endpoints."""

    model_config = ConfigDict(extra="forbid")
    entities: list[Entity]
    relations: list[Relation]

    @model_validator(mode="after")
    def check_endpoints(self) -> "Extraction":
        known = set(self.entities)
        if any(r.source not in known or r.target not in known for r in self.relations):
            raise ValueError("Every relation endpoint must occur in entities")
        return self

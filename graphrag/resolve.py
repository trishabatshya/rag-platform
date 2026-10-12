"""Typed fuzzy resolution with explicit nickname normalization and reviewable merges."""

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from rapidfuzz.fuzz import token_set_ratio

from app.embed import embed
from graphrag.schema import Entity


def normalized(entity: Entity) -> str:
    """Normalize case/spacing/punctuation, with one documented person nickname alias."""
    text = unicodedata.normalize("NFKC", entity.name).casefold()
    words = re.sub(r"[^\w\s]", " ", text).split()
    if entity.type == "PERSON" and len(words) >= 2 and words[0] == "chris":
        words[0] = "christopher"
    return " ".join(words)


@dataclass(frozen=True)
class Resolution:
    """Raw typed entity to canonical entity, and the complete groups for review."""

    mapping: dict[Entity, Entity]
    groups: list[list[Entity]]

    def report(self, path: Path, mode: str) -> None:
        """Write every nontrivial merge group with raw/canonical entity counts."""
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            f"Mode: {'MOCK (not a result)' if mode == 'mock' else 'REAL'}",
            f"Raw entities: {len(self.mapping)}",
            f"Canonical entities: {len(set(self.mapping.values()))}",
        ]
        for group in self.groups:
            if len(group) > 1:
                lines.append(
                    f"{group[0].type}: {', '.join(e.name for e in group)} "
                    f"-> {self.mapping[group[0]].name}"
                )
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def resolve(entities: list[Entity], embedding_pass: bool = False) -> Resolution:
    """Merge same-type names at >=92, longest canonical; optional cosine >=0.97 pass.

    Complete-link groups prevent a fuzzy chain from joining mutually dissimilar names.
    Fuzzy subset matches remain a risk and require human review.
    """
    unique = sorted(set(entities), key=lambda e: (e.type, -len(e.name), e.name))
    vectors = embed([normalized(e) for e in unique]) if embedding_pass else None
    indices = {e: i for i, e in enumerate(unique)}

    def similar(a: Entity, b: Entity) -> bool:
        if a.type != b.type:
            return False
        if token_set_ratio(normalized(a), normalized(b)) >= 92:
            return True
        return bool(
            vectors is not None and np.dot(vectors[indices[a]], vectors[indices[b]]) >= 0.97
        )

    groups: list[list[Entity]] = []
    for entity in unique:
        group = next((g for g in groups if all(similar(entity, e) for e in g)), None)
        if group is None:
            groups.append([entity])
        else:
            group.append(entity)
    mapping = {entity: group[0] for group in groups for entity in group}
    return Resolution(mapping, groups)

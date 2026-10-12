"""Namespaced Neo4j and NetworkX stores with the same evidence-bearing graph interface."""

import os
from collections import Counter
from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

import networkx as nx
import numpy as np

from graphrag.dataset import Paragraph
from graphrag.schema import Entity, Extraction, Relation


@dataclass(frozen=True)
class Hit:
    """A paragraph and a score (vector similarity or expansion path count)."""

    paragraph: Paragraph
    score: float


@dataclass(frozen=True)
class Triple:
    """A typed relation with the chunk that supports it."""

    relation: Relation
    chunk_id: str


class GraphStore(Protocol):
    """Operations shared by local tests and external Neo4j retrieval."""

    def load(
        self, paragraphs: list[Paragraph], vectors: np.ndarray, extractions: dict[str, Extraction]
    ) -> None: ...
    def vector_search(self, vector: np.ndarray, limit: int = 15) -> list[Hit]: ...
    def expand(self, entities: list[Entity], hops: int = 2, limit: int = 20) -> list[Hit]: ...
    def triples(self, chunk_ids: list[str], limit: int = 10) -> list[Triple]: ...
    def close(self) -> None: ...


def _validate_vectors(paragraphs: list[Paragraph], vectors: np.ndarray) -> None:
    if vectors.shape != (len(paragraphs), 384) or not np.isfinite(vectors).all():
        raise ValueError("Expected finite (paragraphs,384) vectors")
    if len({p.id for p in paragraphs}) != len(paragraphs):
        raise ValueError("Duplicate paragraph IDs")


class MemoryGraphStore:
    """NetworkX MultiDiGraph; expansion enumerates relationship-unique paths up to two hops."""

    def __init__(self) -> None:
        self.graph = nx.MultiDiGraph()
        self.paragraphs: dict[str, Paragraph] = {}
        self.vectors: dict[str, np.ndarray] = {}
        self.mentions: dict[Entity, set[str]] = {}

    def load(
        self, paragraphs: list[Paragraph], vectors: np.ndarray, extractions: dict[str, Extraction]
    ) -> None:
        """Replace this owned index; REL keys retain independent chunk evidence."""
        _validate_vectors(paragraphs, vectors)
        self.close()
        self.paragraphs = {p.id: p for p in paragraphs}
        self.vectors = {p.id: v for p, v in zip(paragraphs, vectors, strict=True)}
        for chunk_id, extraction in extractions.items():
            for entity in extraction.entities:
                self.graph.add_node(entity)
                self.mentions.setdefault(entity, set()).add(chunk_id)
            for r in extraction.relations:
                self.graph.add_edge(
                    r.source, r.target, key=(r.type, chunk_id), relation=r, chunk_id=chunk_id
                )

    def vector_search(self, vector: np.ndarray, limit: int = 15) -> list[Hit]:
        """Return exact cosine order; embeddings are normalized by the shared embed adapter."""
        hits = [
            Hit(self.paragraphs[key], float(np.dot(v, vector))) for key, v in self.vectors.items()
        ]
        return sorted(hits, key=lambda h: (-h.score, h.paragraph.id))[:limit]

    def expand(self, entities: list[Entity], hops: int = 2, limit: int = 20) -> list[Hit]:
        """Traverse undirected REL paths, including zero-hop mentions, never beyond two."""
        if not 0 <= hops <= 2:
            raise ValueError("Expansion supports 0..2 hops")
        paths: Counter[str] = Counter()
        adjacency: dict[Entity, list[tuple[Entity, tuple]]] = {}
        for left, right, key in self.graph.edges(keys=True):
            edge = (left, right, key)
            adjacency.setdefault(left, []).append((right, edge))
            if left != right:
                adjacency.setdefault(right, []).append((left, edge))

        def visit(node: Entity, depth: int, used: frozenset) -> None:
            for chunk_id in self.mentions.get(node, set()):
                paths[chunk_id] += 1
            if depth < hops:
                for neighbor, edge in adjacency.get(node, []):
                    if edge not in used:
                        visit(neighbor, depth + 1, used | {edge})

        for entity in set(entities):
            visit(entity, 0, frozenset())
        return [
            Hit(self.paragraphs[key], float(count))
            for key, count in sorted(paths.items(), key=lambda item: (-item[1], item[0]))[:limit]
        ]

    def triples(self, chunk_ids: list[str], limit: int = 10) -> list[Triple]:
        """Return only triples supported by the supplied evidence, in evidence rank order."""
        ranks = {key: i for i, key in enumerate(chunk_ids)}
        rows = [
            Triple(data["relation"], data["chunk_id"])
            for _, _, data in self.graph.edges(data=True)
            if data["chunk_id"] in ranks
        ]
        return sorted(
            rows,
            key=lambda t: (
                ranks[t.chunk_id],
                t.relation.type,
                t.relation.source.name,
                t.relation.target.name,
            ),
        )[:limit]

    def close(self) -> None:
        """Release the owned local index."""
        self.graph.clear()
        self.paragraphs.clear()
        self.vectors.clear()
        self.mentions.clear()


CONSTRAINTS = (
    "CREATE CONSTRAINT graph_entity_key IF NOT EXISTS FOR (e:Entity) "
    "REQUIRE (e.dataset_id, e.name, e.type) IS UNIQUE",
    "CREATE CONSTRAINT graph_chunk_key IF NOT EXISTS FOR (c:Chunk) "
    "REQUIRE (c.dataset_id, c.id) IS UNIQUE",
    "CREATE VECTOR INDEX chunk_embeddings IF NOT EXISTS FOR (c:Chunk) ON c.embedding "
    "OPTIONS {indexConfig: {`vector.dimensions`: 384, `vector.similarity_function`: 'cosine'}}",
)

EXPAND_QUERY = """
MATCH (e:Entity {dataset_id: $dataset_id})
WHERE any(key IN $entities WHERE e.name = key.name AND e.type = key.type)
MATCH (e)-[:REL*0..2]-(n:Entity)<-[:MENTIONS]-(c:Chunk)
WHERE n.dataset_id = $dataset_id AND c.dataset_id = $dataset_id
RETURN c.id AS chunk_id, count(*) AS paths
ORDER BY paths DESC, chunk_id LIMIT $limit
"""


class Neo4jGraphStore:
    """Isolated benchmark namespace; close deletes only nodes owned by this run.

    Neo4j 5 vector ANN lacks pre-filtering: overfetch, namespace-filter, then fall back
    to exact cosine on this run's vectors if fewer than k are found. This is not ACL.
    """

    def __init__(self, uri: str | None = None, driver=None) -> None:
        from neo4j import GraphDatabase

        self.dataset_id = "graph_run_" + uuid4().hex
        self.driver = driver or GraphDatabase.driver(
            uri or os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "devpassword")),
            connection_timeout=10,
        )
        self.local = MemoryGraphStore()
        self.loaded = False

    def _run(self, query: str, **parameters) -> list[dict]:
        with self.driver.session() as session:
            return session.run(query, dataset_id=self.dataset_id, **parameters).data()

    def load(
        self, paragraphs: list[Paragraph], vectors: np.ndarray, extractions: dict[str, Extraction]
    ) -> None:
        """MERGE typed entities, paragraph embeddings, mentions and evidence-bearing RELs."""
        _validate_vectors(paragraphs, vectors)
        for query in CONSTRAINTS:
            self._run(query)
        self.loaded = True  # Partial writes also belong to this run and must be cleaned up.
        self._run("MATCH (n {dataset_id: $dataset_id}) DETACH DELETE n")
        chunks = [
            {"id": p.id, "text": p.text, "title": p.title, "embedding": v.tolist()}
            for p, v in zip(paragraphs, vectors, strict=True)
        ]
        self._run(
            """UNWIND $chunks AS row
MERGE (c:Chunk {dataset_id: $dataset_id, id: row.id})
SET c.text = row.text, c.title = row.title, c.embedding = row.embedding""",
            chunks=chunks,
        )
        mentions, relations = [], []
        for chunk_id, extraction in extractions.items():
            mentions.extend({"chunk_id": chunk_id, **e.model_dump()} for e in extraction.entities)
            relations.extend({"chunk_id": chunk_id, **r.model_dump()} for r in extraction.relations)
        self._run(
            """UNWIND $mentions AS row
MATCH (c:Chunk {dataset_id: $dataset_id, id: row.chunk_id})
MERGE (e:Entity {dataset_id: $dataset_id, name: row.name, type: row.type})
MERGE (c)-[:MENTIONS]->(e)""",
            mentions=mentions,
        )
        self._run(
            """UNWIND $relations AS row
MATCH (a:Entity {dataset_id: $dataset_id, name: row.source.name, type: row.source.type})
MATCH (b:Entity {dataset_id: $dataset_id, name: row.target.name, type: row.target.type})
MERGE (a)-[:REL {type: row.type, chunk_id: row.chunk_id}]->(b)""",
            relations=relations,
        )
        self._run("CALL db.awaitIndex('chunk_embeddings', 60)")
        self.local.load(paragraphs, vectors, extractions)

    def vector_search(self, vector: np.ndarray, limit: int = 15) -> list[Hit]:
        """Query the 384-d cosine index with namespace filtering and starvation fallback."""
        rows = self._run(
            """CALL db.index.vector.queryNodes('chunk_embeddings', $k, $vector)
YIELD node, score WHERE node.dataset_id = $dataset_id
RETURN node.id AS chunk_id, score ORDER BY score DESC, chunk_id LIMIT $limit""",
            k=max(limit * 4, len(self.local.paragraphs)),
            vector=vector.tolist(),
            limit=limit,
        )
        if len(rows) < min(limit, len(self.local.paragraphs)):
            return self.local.vector_search(vector, limit)
        return [Hit(self.local.paragraphs[r["chunk_id"]], r["score"]) for r in rows]

    def expand(self, entities: list[Entity], hops: int = 2, limit: int = 20) -> list[Hit]:
        """Run the bounded Cypher expansion over typed, namespaced entity links."""
        if not 0 <= hops <= 2:
            raise ValueError("Expansion supports 0..2 hops")
        query = EXPAND_QUERY.replace("*0..2", f"*0..{hops}")
        return [
            Hit(self.local.paragraphs[r["chunk_id"]], float(r["paths"]))
            for r in self._run(query, entities=[e.model_dump() for e in entities], limit=limit)
        ]

    def triples(self, chunk_ids: list[str], limit: int = 10) -> list[Triple]:
        """Read only relations backed by selected chunks within the owned namespace."""
        rows = self._run(
            """MATCH (a:Entity {dataset_id: $dataset_id})-[r:REL]->(b:Entity)
WHERE b.dataset_id = $dataset_id AND r.chunk_id IN $chunk_ids
RETURN a.name AS source, a.type AS source_type, r.type AS type,
b.name AS target, b.type AS target_type, r.chunk_id AS chunk_id""",
            chunk_ids=chunk_ids,
        )
        ranks = {key: i for i, key in enumerate(chunk_ids)}
        rows.sort(key=lambda r: (ranks[r["chunk_id"]], r["type"], r["source"], r["target"]))
        return [
            Triple(
                Relation(
                    source=Entity(name=r["source"], type=r["source_type"]),
                    type=r["type"],
                    target=Entity(name=r["target"], type=r["target_type"]),
                ),
                r["chunk_id"],
            )
            for r in rows[:limit]
        ]

    def close(self) -> None:
        """Remove only this run's nodes and close the driver, including after partial failure."""
        try:
            if self.loaded:
                self._run("MATCH (n {dataset_id: $dataset_id}) DETACH DELETE n")
                self.loaded = False
        finally:
            self.local.close()
            self.driver.close()

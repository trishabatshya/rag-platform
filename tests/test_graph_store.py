"""Path bounds, typed identity, evidence provenance and opt-in Neo4j integration."""

import os
from contextlib import closing

import numpy as np
import pytest

from app.embed import embed
from graphrag.dataset import Paragraph
from graphrag.graph_store import CONSTRAINTS, MemoryGraphStore, Neo4jGraphStore
from graphrag.schema import Entity, Extraction, Relation


def chain():
    entities = [Entity(name=name, type="PERSON") for name in ("Alpha", "Beta", "Gamma", "Delta")]
    paragraphs = [Paragraph(f"p{i}", f"Title{i}", f"Evidence {i}") for i in range(3)]
    extractions = {
        p.id: Extraction(
            entities=entities[i : i + 2],
            relations=[
                Relation(source=entities[i], type="RELATED_TO", target=entities[i + 1]),
            ],
        )
        for i, p in enumerate(paragraphs)
    }
    return entities, paragraphs, extractions


def test_memory_zero_one_two_hops_and_relationship_evidence():
    entities, paragraphs, extractions = chain()
    with closing(MemoryGraphStore()) as store:
        store.load(paragraphs, embed([p.text for p in paragraphs]), extractions)
        assert {h.paragraph.id for h in store.expand([entities[0]], 0)} == {"p0"}
        assert {h.paragraph.id for h in store.expand([entities[0]], 1)} == {"p0", "p1"}
        assert {h.paragraph.id for h in store.expand([entities[0]], 2)} == {"p0", "p1", "p2"}
        assert store.expand([Entity(name="Missing", type="PERSON")]) == []
        triples = store.triples(["p1"])
        assert len(triples) == 1 and triples[0].chunk_id == "p1"
        assert triples[0].relation.source == entities[1]
        assert store.vector_search(embed([paragraphs[1].text])[0], 1)[0].paragraph.id == "p1"
        with pytest.raises(ValueError):
            store.expand(entities, 3)
    assert not store.graph and not store.paragraphs


def test_parallel_evidence_typed_names_and_replace_loading():
    person = Entity(name="Shared", type="PERSON")
    place = Entity(name="Shared", type="PLACE")
    other = Entity(name="Other", type="PERSON")
    paragraphs = [Paragraph(str(i), str(i), str(i)) for i in range(3)]
    extractions = {
        str(i): Extraction(
            entities=[person, other],
            relations=[
                Relation(source=person, type="RELATED_TO", target=other),
            ],
        )
        for i in range(2)
    }
    extractions["2"] = Extraction(entities=[place], relations=[])
    with closing(MemoryGraphStore()) as store:
        store.load(paragraphs, embed([p.text for p in paragraphs]), extractions)
        assert store.graph.number_of_edges() == 2
        assert {h.paragraph.id for h in store.expand([place])} == {"2"}
        assert {t.chunk_id for t in store.triples(["0", "1"])} == {"0", "1"}
        store.load(paragraphs[:1], embed(["0"]), {"0": extractions["0"]})
        assert set(store.paragraphs) == {"0"} and store.graph.number_of_edges() == 1
        with pytest.raises(ValueError):
            store.load(paragraphs, np.zeros((3, 10)), extractions)


class RecordingDriver:
    """Capture parameterized Neo4j operations without a server or Cypher simulator."""

    def __init__(self):
        self.calls = []
        self.closed = False
        self.responses = []

    def session(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def run(self, query, **parameters):
        self.calls.append((query, parameters))
        return self

    def data(self):
        return self.responses.pop(0) if self.responses else []

    def close(self):
        self.closed = True


def test_neo4j_constraints_merges_index_and_namespace_parameter_contract():
    driver = RecordingDriver()
    entities, paragraphs, extractions = chain()
    store = Neo4jGraphStore(driver=driver)
    store.load(paragraphs, embed([p.text for p in paragraphs]), extractions)
    assert [query for query, _ in driver.calls[:3]] == list(CONSTRAINTS)
    assert any("MERGE (a)-[:REL" in q for q, _ in driver.calls)
    assert any("MERGE (c)-[:MENTIONS]" in q for q, _ in driver.calls)
    store.expand(entities[:1], hops=1)
    query, params = driver.calls[-1]
    assert "*0..1" in query and params["entities"] == [entities[0].model_dump()]
    assert store.dataset_id not in query  # All data, including namespace, are parameters.
    store.close()
    query, params = driver.calls[-1]
    assert "MATCH (n {dataset_id: $dataset_id}) DETACH DELETE n" == query
    assert params["dataset_id"] == store.dataset_id and driver.closed


def test_neo4j_ann_starvation_uses_owned_vectors_and_parses_supported_triples():
    driver = RecordingDriver()
    entities, paragraphs, extractions = chain()
    store = Neo4jGraphStore(driver=driver)
    store.load(paragraphs, embed([p.text for p in paragraphs]), extractions)
    assert len(store.vector_search(embed(["Evidence"])[0], 3)) == 3
    assert "node.dataset_id = $dataset_id" in driver.calls[-1][0]
    driver.responses.append([{"chunk_id": "p0", "score": 0.99}])
    assert store.vector_search(embed(["Evidence"])[0], 1)[0].score == 0.99
    driver.responses.append(
        [
            {
                "source": "Alpha",
                "source_type": "PERSON",
                "type": "RELATED_TO",
                "target": "Beta",
                "target_type": "PERSON",
                "chunk_id": "p0",
            }
        ]
    )
    assert store.triples(["p0"])[0].relation.source == entities[0]
    store.close()


@pytest.mark.integration
@pytest.mark.skipif(
    not os.getenv("NEO4J_URI"), reason="NEO4J_URI not set: external integration opt-in"
)
def test_live_neo4j_index_and_networkx_expansion_parity():
    """Fail visibly when opted-in service is unavailable; never silently fall back to mock."""
    entities, paragraphs, extractions = chain()
    vectors = embed([p.text for p in paragraphs])
    with closing(Neo4jGraphStore()) as real, closing(MemoryGraphStore()) as memory:
        real.load(paragraphs, vectors, extractions)
        memory.load(paragraphs, vectors, extractions)
        for hops in range(3):
            expected = {h.paragraph.id: h.score for h in memory.expand(entities[:1], hops)}
            assert {h.paragraph.id: h.score for h in real.expand(entities[:1], hops)} == expected
        assert len(real.vector_search(vectors[0], 2)) == 2
        assert real.vector_search(vectors[0], 1)[0].paragraph.id == "p0"
        assert real.triples(["p0", "p1"]) == memory.triples(["p0", "p1"])

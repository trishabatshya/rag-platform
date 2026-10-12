"""Vector baseline and evidence-bounded entity-linked hybrid retrieval."""

import json
import math
import re
from time import perf_counter

from app.config import Settings
from app.contracts import Chunk, RAGResult
from app.embed import embed
from app.llm import complete
from graphrag.graph_store import GraphStore, Hit, Triple
from graphrag.resolve import Resolution
from graphrag.schema import Entity

_cross_encoder = None


def link_entities(question: str, resolution: Resolution) -> list[Entity]:
    """Match complete canonical or alias name phrases with word boundaries (case insensitive)."""
    names = []
    for alias, canonical in resolution.mapping.items():
        if re.search(r"(?<!\w)" + re.escape(alias.name) + r"(?!\w)", question, re.I):
            names.append(canonical)
    return sorted(set(names), key=lambda e: (e.type, e.name))


def lexical_score(question: str, text: str) -> float:
    """Deterministic content-word overlap normalized by evidence length, for mock reranking."""
    stop = {"the", "a", "an", "of", "was", "is", "in", "where", "who", "it", "this"}
    q = set(re.findall(r"\w+", question.casefold())) - stop
    t = set(re.findall(r"\w+", text.casefold())) - stop
    return len(q & t) / math.sqrt(max(1, len(t)))


def rerank(question: str, hits: list[Hit], mode: str, limit: int = 6) -> list[Hit]:
    """Score all deduplicated candidates; real mode lazily loads the specified cross-encoder."""
    if not hits:
        return []
    if mode == "mock":
        scores = [lexical_score(question, h.paragraph.text) for h in hits]
    else:
        global _cross_encoder
        if _cross_encoder is None:
            from sentence_transformers import CrossEncoder

            _cross_encoder = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
        scores = _cross_encoder.predict([(question, h.paragraph.text) for h in hits]).tolist()
    ranked = [Hit(hit.paragraph, float(score)) for hit, score in zip(hits, scores, strict=True)]
    return sorted(ranked, key=lambda h: (-h.score, h.paragraph.id))[:limit]


def relevant_triples(store: GraphStore, hits: list[Hit], linked: list[Entity]) -> list[Triple]:
    """Keep selected-evidence triples within two hops of linked entities; cap at ten."""
    triples = store.triples([h.paragraph.id for h in hits], limit=100)
    reached = set(linked)
    for _ in range(2):
        reached |= {
            endpoint
            for t in triples
            if t.relation.source in reached or t.relation.target in reached
            for endpoint in (t.relation.source, t.relation.target)
        }
    return [t for t in triples if t.relation.source in reached and t.relation.target in reached][
        :10
    ]


class GraphPipeline:
    """Standalone public-corpus short answers, using the existing RAG response shape."""

    def __init__(self, store: GraphStore, resolution: Resolution) -> None:
        self.store, self.resolution = store, resolution
        self.settings = Settings()

    def retrieve(self, question: str, system: str) -> tuple[list[Hit], list[Triple]]:
        """Vector top15 or vector+bounded graph expansion, reranked to six evidence chunks."""
        if system not in {"vector", "graph_hybrid"}:
            raise ValueError("system must be vector|graph_hybrid")
        vector_hits = self.store.vector_search(embed([question])[0], 15)
        if system == "vector":
            # A plain vector baseline, with the same six-chunk generation budget.
            return vector_hits[:6], []
        linked = link_entities(question, self.resolution)
        expanded = self.store.expand(linked, hops=2, limit=20)
        by_id = {h.paragraph.id: h for h in vector_hits + expanded}
        # Expand the reranker question with names reached by the graph, in both modes.
        # This gives the lexical mock a meaningful stand-in for semantic bridge matching.
        graph_triples = relevant_triples(self.store, expanded, linked)
        names = sorted(
            {e.name for t in graph_triples for e in (t.relation.source, t.relation.target)}
        )
        rerank_question = question + (" Related entities: " + "; ".join(names) if names else "")
        hits = rerank(rerank_question, list(by_id.values()), self.settings.mode)
        return hits, relevant_triples(self.store, hits, linked)

    def answer(
        self, question: str, system: str = "graph_hybrid", model: str | None = None
    ) -> RAGResult:
        """Generate a short phrase from evidence only, including abstention when unsupported."""
        start = perf_counter()
        model = model or self.settings.large_model
        hits, triples = self.retrieve(question, system)
        prompt = json.dumps(
            {
                "instruction": "Return a short answer phrase only. No explanation or citations. "
                "Use only provided evidence. If unsupported return I don't know.",
                "question": question,
                "paragraphs": [
                    {"id": h.paragraph.id, "title": h.paragraph.title, "text": h.paragraph.text}
                    for h in hits
                ],
                "triples": [{"chunk_id": t.chunk_id, **t.relation.model_dump()} for t in triples],
            }
        )
        response = complete(prompt, model, system="GRAPH_ANSWER")
        chunks: list[Chunk] = [
            {
                "id": h.paragraph.id,
                "score": h.score,
                "text": h.paragraph.text,
                "source": h.paragraph.title,
                "doc_id": h.paragraph.id,
            }
            for h in hits
        ]
        return {
            "answer": response.text.strip(),
            "sources": sorted({c["source"] for c in chunks}),
            "chunks": chunks,
            "model": response.model,
            "in_tokens": response.in_tokens,
            "out_tokens": response.out_tokens,
            "latency_ms": (perf_counter() - start) * 1000,
        }

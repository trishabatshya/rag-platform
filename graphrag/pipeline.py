"""Configurable standalone public multi-hop entry point, isolated from authenticated tenant RAG."""

import argparse
import json
import logging

from app.config import Settings
from app.contracts import CurrentUser, RAGResult
from graphrag.dataset import load_dataset_corpus
from graphrag.index import build_index
from graphrag.retrieve import GraphPipeline

_owned: GraphPipeline | None = None
_owned_key: tuple | None = None


def get_pipeline(
    source: str = "fixture", n: int = 150, seed: int = 42, fallback: bool = True
) -> GraphPipeline:
    """Own one public index; replacing source requires closing the previous pipeline first."""
    global _owned, _owned_key
    settings = Settings()
    if settings.mode == "mock" and source != "fixture":
        raise ValueError("Mock graph extraction requires the annotated fixture")
    key = (source, n, seed, fallback, settings)
    if _owned is not None and _owned_key == key:
        return _owned
    close_pipeline()
    corpus = load_dataset_corpus(source, n=n, seed=seed, fallback=fallback)
    logging.getLogger(__name__).info(
        "Graph corpus: %s; fallback: %s", corpus.origin, corpus.fallback_reason or "none"
    )
    _owned = build_index(corpus)[0]
    _owned_key = key
    return _owned


def rag_pipeline(question: str, model: str, user: CurrentUser | None = None) -> RAGResult:
    """Use RETRIEVAL_MODE for the public fixture, rejecting tenant identity before indexing."""
    if user is not None:
        raise PermissionError("The public graph has no ACLs; use app.service for tenant requests")
    if not question.strip():
        raise ValueError("Question must not be empty")
    return get_pipeline().answer(question.strip(), system=Settings().retrieval_mode, model=model)


def close_pipeline() -> None:
    """Close the owned graph and clear the cache without creating an index at shutdown."""
    global _owned, _owned_key
    if _owned is not None:
        try:
            _owned.store.close()
        finally:
            _owned = _owned_key = None


def main() -> None:
    """Run a question on an explicitly public corpus and close storage on every exit."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question")
    parser.add_argument("--dataset", choices=("fixture", "hotpotqa"), default="fixture")
    parser.add_argument("--n", type=int, default=150)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--no-fallback", action="store_true")
    args = parser.parse_args()
    settings = Settings()
    try:
        pipeline = get_pipeline(args.dataset, args.n, args.seed, not args.no_fallback)
        response = pipeline.answer(args.question, system=settings.retrieval_mode)
        print(
            json.dumps(
                {
                    "mode": "MOCK (not a result)" if settings.mode == "mock" else "REAL",
                    "dataset": pipeline.origin,
                    "retrieval_mode": settings.retrieval_mode,
                    "response": response,
                },
                indent=2,
            )
        )
    finally:
        close_pipeline()


if __name__ == "__main__":
    main()

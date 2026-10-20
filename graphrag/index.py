"""Build one shared vector/graph corpus and its independently accounted indexing usage."""

import hashlib
import json
import sys
from dataclasses import asdict
from pathlib import Path
from time import perf_counter

from app.config import Settings
from app.embed import embed
from graphrag.dataset import Corpus
from graphrag.extract import ExtractionUnavailable, Extractor
from graphrag.graph_store import GraphStore, MemoryGraphStore, Neo4jGraphStore
from graphrag.resolve import resolve
from graphrag.retrieve import GraphPipeline
from graphrag.schema import Extraction, Relation


def build_index(
    corpus: Corpus,
    cache_dir: Path | None = None,
    report_path: Path | None = None,
    embedding_resolution: bool = False,
    store: GraphStore | None = None,
    fresh_extraction: bool = False,
) -> tuple[GraphPipeline, dict]:
    """Extract/resolve once and index all paragraphs; failed extraction retains vector evidence."""
    start = perf_counter()
    settings = Settings()
    extractor = Extractor(
        cache_dir,
        failure_log=report_path.parent / "extraction_failures.log" if report_path else None,
        fresh_extraction=fresh_extraction,
    )
    extractions = {}
    label = "MOCK (not a result)" if settings.mode == "mock" else "REAL"
    total = len(corpus.paragraphs)
    try:
        for done, paragraph in enumerate(corpus.paragraphs, 1):
            extraction = extractor.extract(paragraph)
            if extraction is not None:
                extractions[paragraph.id] = extraction
            if done % 10 == 0 or done == total:
                print(
                    f"Extraction [{label}] {done}/{total} "
                    f"failures={extractor.usage.failed_chunks} "
                    f"elapsed={perf_counter() - start:.1f}s",
                    file=sys.stderr,
                    flush=True,
                )
    except ExtractionUnavailable as exc:
        exc.indexing = asdict(extractor.usage)
        exc.indexing["first_fill_extraction"] = extractor.first_fill_summary()
        raise
    finally:
        if report_path:
            extractor.write_skipped(report_path.parent / "skipped_chunks.txt")
    resolution = resolve(
        [e for x in extractions.values() for e in x.entities], embedding_resolution
    )
    resolved = {}
    for key, extraction in extractions.items():
        resolved[key] = Extraction(
            entities=sorted(
                {resolution.mapping[e] for e in extraction.entities}, key=lambda e: (e.type, e.name)
            ),
            relations=[
                Relation(
                    source=resolution.mapping[r.source],
                    type=r.type,
                    target=resolution.mapping[r.target],
                )
                for r in extraction.relations
            ],
        )
    if report_path:
        resolution.report(report_path, settings.mode)
    store = store or (MemoryGraphStore() if settings.mode == "mock" else Neo4jGraphStore())
    try:
        store.load(corpus.paragraphs, embed([p.text for p in corpus.paragraphs]), resolved)
    except Exception:
        store.close()
        raise
    usage = {
        **asdict(extractor.usage),
        "total_indexing_ms": (perf_counter() - start) * 1000,
        "paragraph_count": len(corpus.paragraphs),
        "raw_entities": len(resolution.mapping),
        "canonical_entities": len(set(resolution.mapping.values())),
        "embedding_resolution": embedding_resolution,
        "merge_counts": resolution.merge_counts,
        "first_fill_extraction": extractor.first_fill_summary(),
        "fresh_extraction": fresh_extraction,
        "graph_fingerprint": hashlib.sha256(
            json.dumps(
                {key: value.model_dump() for key, value in resolved.items()}, sort_keys=True
            ).encode()
        ).hexdigest(),
        "cost_scope": "new extraction LLM tokens at reference prices; "
        "excludes embeddings, reranker, storage and local compute charges",
    }
    return GraphPipeline(store, resolution, origin=corpus.origin), usage

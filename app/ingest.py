"""Paragraph-aware chunking and idempotent, versioned folder ingestion."""

import argparse
import json
import re
from contextlib import closing
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from qdrant_client import QdrantClient, models

from app.access_models import ACLDocument
from app.config import Settings
from app.corpus_state import CorpusState
from app.embed import embed
from app.vectorstore import create_client, ensure_acl_indexes, ensure_collection


def chunk_text(text: str, size: int = 400, overlap: int = 60) -> list[str]:
    """Split at paragraph boundaries where possible, retaining exact word overlap."""
    if size <= 0 or overlap < 0 or overlap >= size:
        raise ValueError("Require size > overlap >= 0")
    if not text.strip():
        return []
    paragraphs = re.split(r"\n\s*\n", text.strip())
    words: list[str] = []
    boundaries: list[int] = []
    for paragraph in paragraphs:
        words.extend(paragraph.split())
        boundaries.append(len(words))
    if len(words) <= size:
        return [text.strip()]
    chunks = []
    start = 0
    while start < len(words):
        end = min(start + size, len(words))
        if end < len(words):
            candidates = [boundary for boundary in boundaries if start + overlap < boundary <= end]
            if candidates:
                end = candidates[-1]
        chunks.append(" ".join(words[start:end]))
        if end == len(words):
            break
        start = end - overlap
    return chunks


def document_paths(folder: Path) -> list[Path]:
    """Find supported UTF-8 documents recursively in a deterministic order."""
    if not folder.is_dir():
        raise ValueError(f"Document directory does not exist: {folder}")
    return sorted(path for path in folder.rglob("*") if path.suffix.lower() in {".md", ".txt"})


def ingest_folder(
    folder: Path, client: QdrantClient, state: CorpusState, *, collection: str = "baseline_chunks"
) -> dict[str, int]:
    """Replace this folder's documents, remove stale chunks, and advance corpus version."""
    if collection == "chunks":
        raise ValueError("The ACL collection requires ingest_acl_documents with explicit metadata")
    folder = folder.resolve()
    files = document_paths(folder)
    if not files:
        raise ValueError(f"No .md or .txt documents found: {folder}")
    folder_key = folder.as_posix()
    prepared: list[tuple[str, list[models.PointStruct]]] = []
    # Prepare and embed all evidence before mutating the index.
    for path in files:
        source = path.relative_to(folder).as_posix()
        doc_id = str(uuid5(NAMESPACE_URL, f"{folder_key}/{source}"))
        texts = chunk_text(path.read_text(encoding="utf-8"))
        vectors = embed(texts)
        points = [
            models.PointStruct(
                id=str(uuid5(NAMESPACE_URL, f"{doc_id}/{number}")),
                vector=vector.tolist(),
                payload={"text": text, "source": source, "doc_id": doc_id, "chunk_no": number},
            )
            for number, (text, vector) in enumerate(zip(texts, vectors, strict=True))
        ]
        prepared.append((doc_id, points))
    ensure_collection(client, collection)
    with state.connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        version = (
            int(connection.execute("SELECT version FROM corpus_state WHERE id=1").fetchone()[0]) + 1
        )
        previous = {
            row[0]
            for row in connection.execute(
                "SELECT doc_id FROM documents WHERE folder=?", (folder_key,)
            )
        }
        current = {doc_id for doc_id, _ in prepared}
        for doc_id in sorted(previous | current):
            client.delete(
                collection,
                points_selector=models.FilterSelector(
                    filter=models.Filter(
                        must=[
                            models.FieldCondition(
                                key="doc_id", match=models.MatchValue(value=doc_id)
                            )
                        ]
                    )
                ),
                wait=True,
            )
        for _, points in prepared:
            for point in points:
                point.payload["corpus_version"] = version
            for start in range(0, len(points), 128):
                client.upsert(collection, points[start : start + 128], wait=True)
        connection.execute("DELETE FROM documents WHERE folder=?", (folder_key,))
        connection.executemany(
            "INSERT INTO documents VALUES(?, ?)", [(folder_key, doc) for doc in sorted(current)]
        )
        connection.execute("UPDATE corpus_state SET version=? WHERE id=1", (version,))
    return {
        "documents": len(files),
        "chunks": sum(len(points) for _, points in prepared),
        "corpus_version": version,
    }


def ingest_acl_documents(
    documents: list[dict],
    client: QdrantClient,
    state: CorpusState,
    *,
    namespace: str = "seed",
    collection: str = "chunks",
) -> dict[str, int]:
    """Validate all ACLs before writes, then replace this namespace's ACL documents."""
    validated = [ACLDocument.model_validate(document) for document in documents]
    if len({document.doc_id for document in validated}) != len(validated):
        raise ValueError("ACL document IDs must be unique")
    prepared = []
    for document in validated:
        texts = chunk_text(document.text)
        vectors = embed(texts)
        metadata = document.model_dump(exclude={"text"})
        points = [
            models.PointStruct(
                id=str(uuid5(NAMESPACE_URL, f"secure/{document.doc_id}/{number}")),
                vector=vector.tolist(),
                payload={**metadata, "text": text, "chunk_no": number},
            )
            for number, (text, vector) in enumerate(zip(texts, vectors, strict=True))
        ]
        prepared.append((document.doc_id, points))
    if collection == "baseline_chunks":
        raise ValueError("ACL documents cannot be written into the public baseline collection")
    ensure_collection(client, collection)
    ensure_acl_indexes(client, collection)
    folder_key = f"acl:{collection}:{namespace}"
    with state.access_lock, state.connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        version = (
            int(connection.execute("SELECT version FROM corpus_state WHERE id=1").fetchone()[0]) + 1
        )
        previous = {
            row[0]
            for row in connection.execute(
                "SELECT doc_id FROM documents WHERE folder=?", (folder_key,)
            )
        }
        current = {doc_id for doc_id, _ in prepared}
        for doc_id in previous | current:
            client.delete(
                collection,
                models.Filter(
                    must=[
                        models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id))
                    ]
                ),
                wait=True,
            )
        for _, points in prepared:
            for point in points:
                point.payload["corpus_version"] = version
            for offset in range(0, len(points), 128):
                client.upsert(collection, points[offset : offset + 128], wait=True)
        connection.execute("DELETE FROM documents WHERE folder=?", (folder_key,))
        connection.executemany(
            "INSERT INTO documents VALUES(?, ?)", [(folder_key, doc) for doc in sorted(current)]
        )
        connection.execute("UPDATE corpus_state SET version=? WHERE id=1", (version,))
    return {
        "documents": len(validated),
        "chunks": sum(len(points) for _, points in prepared),
        "corpus_version": version,
    }


def main() -> None:
    """Ingest the configured corpus; mock indexes last for this process only."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docs", type=Path, default=Settings().docs_dir)
    parser.add_argument("--corpus", choices=["baseline", "seed", "all"], default="all")
    args = parser.parse_args()
    with closing(create_client()) as client:
        state = CorpusState(Settings().state_db)
        result = {}
        if args.corpus in {"baseline", "all"}:
            result["baseline"] = ingest_folder(args.docs, client, state)
        if args.corpus in {"seed", "all"}:
            documents = json.loads(
                (Settings().seed_dir / "documents.json").read_text(encoding="utf-8")
            )
            result["seed"] = ingest_acl_documents(documents, client, state)
    print(json.dumps({"mode": Settings().mode, **result}))
    if Settings().mode == "mock":
        print("MOCK: in-memory index ends with this process; service/eval reload the corpus.")


if __name__ == "__main__":
    main()

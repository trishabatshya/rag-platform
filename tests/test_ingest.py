"""Chunk boundaries, idempotency, version persistence and stale evidence removal."""

from contextlib import closing

import pytest

from app.config import Settings
from app.corpus_state import CorpusState
from app.ingest import chunk_text, ingest_folder
from app.vectorstore import create_client


@pytest.mark.parametrize("text", ["", " \n\t", "\n\n"])
def test_empty_document(text):
    assert chunk_text(text) == []


def test_short_document():
    assert chunk_text("  A short paragraph.\n\nAnd another.  ") == [
        "A short paragraph.\n\nAnd another."
    ]


@pytest.mark.parametrize("size,overlap", [(0, 0), (10, 10), (10, -1)])
def test_bad_chunk_settings(size, overlap):
    with pytest.raises(ValueError):
        chunk_text("sample", size, overlap)


def test_long_document_overlap_and_coverage():
    words = [f"word{i}" for i in range(1037)]
    chunks = chunk_text(" ".join(words))
    reconstructed = chunks[0].split()
    for previous, current in zip(chunks, chunks[1:]):
        assert previous.split()[-60:] == current.split()[:60]
        reconstructed.extend(current.split()[60:])
    assert reconstructed == words
    assert all(len(chunk.split()) <= 400 for chunk in chunks)


def test_paragraph_boundary_and_overlap():
    words = [f"word{i}" for i in range(650)]
    text = (
        " ".join(words[:250]) + "\n\n" + " ".join(words[250:450]) + "\n\n" + " ".join(words[450:])
    )
    chunks = chunk_text(text)
    assert len(chunks[0].split()) == 250
    assert chunks[0].split()[-60:] == chunks[1].split()[:60]
    assert all(len(chunk.split()) <= 400 for chunk in chunks)


def test_ingestion_version_count_and_payload(tmp_path):
    folder = tmp_path / "Company docs with spaces"
    (folder / "Nested notes").mkdir(parents=True)
    (folder / "a.md").write_text("Northwind storage is 20 GB.", encoding="utf-8")
    (folder / "Nested notes" / "unicode.txt").write_text(
        "Résumé and 東京 documents.", encoding="utf-8"
    )
    (folder / "empty.md").write_text("", encoding="utf-8")
    state = CorpusState(Settings().state_db)
    with closing(create_client()) as client:
        first = ingest_folder(folder, client, state)
        assert first == {"documents": 3, "chunks": 2, "corpus_version": 1}
        points, _ = client.scroll("baseline_chunks", limit=20)
        ids = {point.id for point in points}
        assert {point.payload["source"] for point in points} == {"a.md", "Nested notes/unicode.txt"}
        assert all(
            {"text", "source", "doc_id", "chunk_no", "corpus_version"} <= point.payload.keys()
            for point in points
        )
        assert ingest_folder(folder, client, state)["corpus_version"] == 2
        points, _ = client.scroll("baseline_chunks", limit=20)
        assert {point.id for point in points} == ids
        assert all(point.payload["corpus_version"] == 2 for point in points)
        assert CorpusState(Settings().state_db).version == 2


def test_shortened_and_deleted_documents_leave_no_stale_chunks(tmp_path):
    folder = tmp_path / "docs"
    folder.mkdir()
    long = folder / "long.md"
    removed = folder / "removed.md"
    long.write_text(" ".join(f"token{i}" for i in range(950)), encoding="utf-8")
    removed.write_text("Obsolete document", encoding="utf-8")
    state = CorpusState(Settings().state_db)
    with closing(create_client()) as client:
        first = ingest_folder(folder, client, state)
        assert client.count("baseline_chunks").count == first["chunks"] == 4
        long.write_text("Short replacement", encoding="utf-8")
        removed.unlink()
        assert ingest_folder(folder, client, state)["chunks"] == 1
        points, _ = client.scroll("baseline_chunks", limit=20)
        assert len(points) == 1 and points[0].payload["text"] == "Short replacement"


def test_preparation_failure_does_not_change_index_or_version(tmp_path):
    folder = tmp_path / "docs"
    folder.mkdir()
    path = folder / "a.md"
    path.write_text("Good original document", encoding="utf-8")
    state = CorpusState(Settings().state_db)
    with closing(create_client()) as client:
        ingest_folder(folder, client, state)
        path.write_bytes(b"\xff")
        with pytest.raises(UnicodeDecodeError):
            ingest_folder(folder, client, state)
        assert state.version == 1
        assert client.scroll("baseline_chunks")[0][0].payload["text"] == "Good original document"


def test_missing_or_empty_folder(tmp_path):
    state = CorpusState(Settings().state_db)
    with closing(create_client()) as client:
        with pytest.raises(ValueError):
            ingest_folder(tmp_path / "missing", client, state)
        with pytest.raises(ValueError):
            ingest_folder(tmp_path, client, state)
        assert state.version == 0

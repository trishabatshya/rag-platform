"""Offline corpus fetch and candidate generation, including review protections."""

import json
from urllib.error import URLError

import pytest

from app.config import ROOT
from scripts.fetch_corpus import fetch_corpus
from scripts.gen_eval import generate_candidates


def test_fetch_gracefully_skips_network_failures_and_unsupported_urls(monkeypatch, tmp_path):
    import scripts.fetch_corpus as module

    def offline(*args, **kwargs):
        raise URLError("offline")

    monkeypatch.setattr(module, "urlopen", offline)
    urls = tmp_path / "URLs.txt"
    urls.write_text(
        "# comment\nhttps://example.invalid/doc.md\nfile:///private/file.txt\n", encoding="utf-8"
    )
    result = fetch_corpus(urls, tmp_path / "Fetched docs")
    assert len(result) == 2 and all(item["status"] == "skipped" for item in result)
    assert not list((tmp_path / "Fetched docs").iterdir())


def test_fetch_writes_success_even_if_another_url_fails(monkeypatch, tmp_path):
    from email.message import Message
    from io import BytesIO

    import scripts.fetch_corpus as module

    def response(request, **kwargs):
        if request.full_url.endswith("bad"):
            raise URLError("offline")
        stream = BytesIO("Résumé document".encode())
        stream.headers = Message()
        stream.headers["Content-Type"] = "text/plain; charset=utf-8"
        return stream

    monkeypatch.setattr(module, "urlopen", response)
    urls = tmp_path / "urls.txt"
    urls.write_text("https://example.invalid/good\nhttps://example.invalid/bad", encoding="utf-8")
    results = fetch_corpus(urls, tmp_path / "outputs")
    assert [result["status"] for result in results] == ["downloaded", "skipped"]
    assert (
        next((tmp_path / "outputs").glob("*.txt")).read_text(encoding="utf-8") == "Résumé document"
    )


def test_candidate_generator_uses_mock_llm_and_marks_every_item(tmp_path):
    output = tmp_path / "Candidate review" / "items.jsonl"
    count = generate_candidates(ROOT / "data" / "docs_sample", output)
    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert count == len(rows) == 20
    assert all(row["needs_review"] and row["mode"] == "MOCK" for row in rows)
    assert len({row["id"] for row in rows}) == 20
    with pytest.raises(FileExistsError):
        generate_candidates(ROOT / "data" / "docs_sample", output)
    with pytest.raises(ValueError, match="Never overwrite"):
        generate_candidates(ROOT / "data" / "docs_sample", ROOT / "data" / "eval.jsonl")

"""Fixed-schema constrained generation, lenient repair and concise diagnostics."""

import json
from typing import get_args

import pytest

from app.llm import LLMResult, complete
from graphrag.dataset import load_fixture
from graphrag.extract import ENTITY_ALIASES, Extractor, repair_extraction
from graphrag.schema import EntityType, RelationType


@pytest.mark.parametrize("kind,expected", [*ENTITY_ALIASES.items(), ("OIL_FIELD", "OTHER")])
def test_aliases_and_fallback_keep_fixed_types(kind, expected):
    result, counts, repaired = repair_extraction(
        {"entities": [{"name": "Example", "type": kind}], "relations": []}
    )
    assert result.entities[0].type == expected and repaired
    assert counts["repaired_entity_types"] == 1


def test_string_entities_empty_names_unknown_relations_and_endpoints():
    result, counts, repaired = repair_extraction(
        {
            "entities": ["Alice", {"name": "Film", "type": "MOVIE"}, "   "],
            "relations": [
                {
                    "source": "Alice",
                    "target": {"name": "Film", "type": "MOVIE"},
                    "type": "PRODUCED_BY",
                },
                {"source": "Alice", "target": "Absent", "type": "OWNED_BY"},
            ],
        }
    )
    assert repaired and len(result.entities) == 2 and len(result.relations) == 1
    assert result.entities[0].type == "OTHER" and result.entities[1].type == "WORK"
    assert result.relations[0].type == "RELATED_TO"
    assert counts["repaired_relation_types"] == 2 and counts["dropped_relations"] == 1
    assert counts["dropped_entities"] == 1
    assert counts["repaired_entity_types"] == 2  # declared entity and typed endpoint
    assert get_args(EntityType) == ("PERSON", "ORG", "PLACE", "WORK", "EVENT", "OTHER")
    assert get_args(RelationType) == (
        "BORN_IN",
        "DIRECTED",
        "ACTOR_IN",
        "MEMBER_OF",
        "LOCATED_IN",
        "FOUNDED",
        "AUTHORED",
        "PART_OF",
        "RELATED_TO",
    )


def test_schema_forwarding_default_cap_and_repair_counters(monkeypatch, tmp_path):
    monkeypatch.setenv("RAG_MODE", "real")
    monkeypatch.delenv("EXTRACT_MAX_TOKENS", raising=False)
    captured = []

    def completion(prompt, model, **kwargs):
        captured.append((prompt, kwargs))
        return LLMResult('{"entities":["Alice"],"relations":[]}', 10, 5, model, 1)

    monkeypatch.setattr("graphrag.extract.complete", completion)
    extractor = Extractor(tmp_path)
    assert extractor.extract(load_fixture().paragraphs[0]) is not None
    prompt, options = captured[0]
    schema = options["response_format"]["json_schema"]["schema"]
    assert options["response_format"]["type"] == "json_schema"
    assert options["max_tokens"] == 1000
    assert schema["$defs"]["Entity"]["properties"]["type"]["enum"] == list(get_args(EntityType))
    assert schema["properties"]["entities"]["maxItems"] == 8
    assert schema["properties"]["relations"]["maxItems"] == 8
    assert "at most 8 entities and 8 relations" in prompt and "JSON schema:" not in prompt
    assert extractor.usage.chunks_attempted == extractor.usage.extracted_after_repair == 1
    assert extractor.usage.extracted_cleanly == extractor.usage.failed_chunks == 0
    assert extractor.usage.coerced_string_entities == 1


def test_failures_have_one_short_console_line_and_full_disk_details(monkeypatch, tmp_path, caplog):
    monkeypatch.setenv("RAG_MODE", "real")
    raw = '{"entities":[{"name":123,"type":"PERSON"}],"relations":[]}'
    monkeypatch.setattr("graphrag.extract.complete", lambda p, m, **kw: LLMResult(raw, 1, 1, m, 1))
    path = tmp_path / "logs with spaces" / "extraction_failures.log"
    extractor = Extractor(tmp_path / "cache", failure_log=path)
    chunk = load_fixture().paragraphs[0]
    assert extractor.extract(chunk) is None
    assert extractor.usage.chunks_attempted == extractor.usage.failed_chunks == 1
    assert len(caplog.records) == 1 and "validation failure" in caplog.text
    assert "Input should" not in caplog.text and len(caplog.records[0].message) < 150
    details = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(details) == 3 and all(d["raw"] == raw for d in details)
    assert "validation error" in details[0]["error"]
    assert not list(extractor.cache_dir.glob("*.json"))


def test_response_schema_reaches_litellm(monkeypatch):
    import sys
    from types import SimpleNamespace

    monkeypatch.setenv("RAG_MODE", "real")
    schema = {"type": "json_schema", "json_schema": {"schema": {"type": "object"}}}
    captured = []

    def provider(**kwargs):
        captured.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
        )

    monkeypatch.setitem(sys.modules, "litellm", SimpleNamespace(completion=provider))
    complete("extract", "ollama/test", json_mode=True, response_format=schema)
    assert captured[0]["response_format"] == schema

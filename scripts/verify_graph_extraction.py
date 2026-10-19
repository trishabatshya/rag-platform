"""Run three fresh real extraction smoke cases and retain raw, pre-repair evidence."""

import json
from dataclasses import asdict
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import get_args
from unittest.mock import patch
from urllib.request import urlopen

from app.config import ROOT, Settings
from app.llm import complete
from graphrag.dataset import Paragraph
from graphrag.extract import Extractor
from graphrag.schema import Entity, EntityType, Relation, RelationType


def verify(output_dir: Path) -> Path:
    """Check raw schema enums through LiteLLM/Ollama, without embeddings or databases."""
    settings = Settings()
    if settings.mode != "real":
        raise ValueError("Set RAG_MODE=real for this explicitly live smoke check")
    with urlopen(settings.ollama_api_base.rstrip("/") + "/api/version", timeout=5) as handle:
        ollama_version = json.load(handle)["version"]
    paragraphs = [
        "Christopher Nolan directed the movie Inception. Nolan was born in London, England.",
        "The band Radiohead was formed in Abingdon, Oxfordshire, England. "
        "Radiohead released the album OK Computer.",
        "The Kern River Oil Field is located in Kern County, California. "
        "Chevron is a company that operates the field.",
    ]
    raw = []

    def capture(*args, **kwargs):
        response = complete(*args, **kwargs)
        payload = json.loads(response.text)
        # Validate individual objects, not repaired output or endpoint membership.
        for entity in payload["entities"]:
            Entity.model_validate(entity)
        for relation in payload["relations"]:
            Relation.model_validate(relation)
        raw.append(
            {
                "raw": response.text,
                "finish_reason": response.finish_reason,
                "in_tokens": response.in_tokens,
                "out_tokens": response.out_tokens,
                "response_format": kwargs["response_format"],
            }
        )
        return response

    results = []
    with TemporaryDirectory(prefix="graph schema smoke ") as temporary:
        extractor = Extractor(Path(temporary), model="ollama/llama3.2:3b")
        with patch("graphrag.extract.complete", capture):
            for index, text in enumerate(paragraphs, 1):
                result = extractor.extract(Paragraph(f"schema-smoke-{index}", "Smoke", text))
                results.append(
                    {"paragraph": text, "extraction": result.model_dump() if result else None}
                )
                print(f"schema-smoke-{index}: {'extracted' if result else 'FAILED'}", flush=True)
        usage = asdict(extractor.usage)
    report = {
        "mode": "REAL",
        "scope": "three authored smoke paragraphs; not a quality benchmark",
        "litellm_version": version("litellm"),
        "ollama_version": ollama_version,
        "model": "ollama/llama3.2:3b",
        "max_tokens": extractor.max_tokens,
        "entity_types": list(get_args(EntityType)),
        "relation_types": list(get_args(RelationType)),
        "raw_replies": raw,
        "results": results,
        "indexing": usage,
        "raw_schema_types_valid": len(raw) == 3 and all(r["extraction"] for r in results),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"extraction_schema_smoke_{datetime.now(UTC):%Y%m%dT%H%M%S%fZ}.json"
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(path)
    if not report["raw_schema_types_valid"]:
        raise RuntimeError("Three-paragraph raw schema verification failed; inspect saved report")
    return path


if __name__ == "__main__":
    verify(ROOT / "eval" / "results")

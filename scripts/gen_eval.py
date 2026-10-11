"""Generate unreviewed candidate questions without modifying the reviewed evaluation set."""

import argparse
import json
import logging
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from app.config import ROOT, Settings
from app.ingest import document_paths
from app.llm import complete


class Candidate(BaseModel):
    """LLM-produced question and reference, validated before writing."""

    question: str = Field(min_length=1)
    reference: str = Field(min_length=1)


class Candidates(BaseModel):
    """Structured output expected from the generator."""

    items: list[Candidate] = Field(min_length=1)


def generate_candidates(folder: Path, output: Path) -> int:
    """Generate candidates from each document; every item requires human review."""
    if output.resolve() == (ROOT / "data" / "eval.jsonl").resolve():
        raise ValueError("Never overwrite the reviewed data/eval.jsonl")
    rows = []
    for path in document_paths(folder):
        text = path.read_text(encoding="utf-8")
        if not text.strip():
            continue
        result = complete(
            f"Generate evaluation candidates.\nDOCUMENT:\n{text}",
            Settings().large_model,
            system=(
                'Return JSON {"items":[{"question":"...","reference":"..."}]}. '
                "Write two specific questions answered only by the document, "
                "with concise references."
            ),
            json_mode=True,
        )
        try:
            candidates = Candidates.model_validate_json(result.text)
        except ValidationError:
            logging.warning("Invalid candidate JSON for %s; skipping", path)
            continue
        for candidate in candidates.items:
            rows.append(
                {
                    "id": f"candidate-{len(rows) + 1:04d}",
                    "question": candidate.question,
                    "reference": candidate.reference,
                    "source": path.relative_to(folder).as_posix(),
                    "answerable": True,
                    "needs_review": True,
                    "mode": Settings().mode.upper(),
                }
            )
    output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation avoids overwriting an in-progress human review.
    with output.open("x", encoding="utf-8", newline="") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return len(rows)


def main() -> None:
    """Generate candidate JSONL; review each item before promoting it into eval.jsonl."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docs", type=Path, default=Settings().docs_dir)
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "eval_candidates.jsonl")
    args = parser.parse_args()
    count = generate_candidates(args.docs, args.output)
    print(
        f"{Settings().mode.upper()}: wrote {count} candidates to {args.output}; "
        "HUMAN REVIEW REQUIRED."
    )


if __name__ == "__main__":
    main()

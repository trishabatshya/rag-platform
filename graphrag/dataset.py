"""Seeded HotpotQA distractor loading with an explicit offline fixture fallback."""

import json
import logging
import random
from dataclasses import dataclass, field
from pathlib import Path

from app.config import ROOT
from graphrag.schema import Extraction

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Paragraph:
    """One document paragraph; annotations are only for mock extraction."""

    id: str
    title: str
    text: str
    annotation: Extraction | None = None


@dataclass(frozen=True)
class Question:
    """Evaluation labels are separate from indexing and retrieval inputs."""

    id: str
    question: str
    answer: str
    supporting_titles: list[str]
    kind: str
    steps: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Corpus:
    """Paragraphs, evaluation questions and truthful data provenance."""

    paragraphs: list[Paragraph]
    questions: list[Question]
    origin: str
    fallback_reason: str | None = None


def load_fixture(path: Path | None = None, n: int = 150, seed: int = 42) -> Corpus:
    """Load the authored fictional fixture without any network or gold-answer retrieval."""
    if n <= 0:
        raise ValueError("n must be positive")
    path = path or ROOT / "data" / "graph_fixture" / "fixture.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    paragraphs = [
        Paragraph(p["id"], p["title"], p["text"], Extraction.model_validate(p["annotation"]))
        for p in data["paragraphs"]
    ]
    questions = [Question(**q) for q in data["questions"]]
    random.Random(seed).shuffle(questions)
    return Corpus(paragraphs, questions[:n], "fixture")


def _pairs(value: dict | list, keys: tuple[str, str]) -> list:
    if isinstance(value, dict):
        left, right = value[keys[0]], value[keys[1]]
        if len(left) != len(right):
            raise ValueError("Mismatched dataset columns")
        return list(zip(left, right, strict=True))
    return value


def from_hotpot(rows: list[dict]) -> Corpus:
    """Accept current dict-of-lists and historical pair-list context/support fields."""
    paragraphs: dict[tuple[str, str], Paragraph] = {}
    title_counts: dict[str, int] = {}
    questions = []
    for row in rows:
        titles = sorted({p[0] for p in _pairs(row["supporting_facts"], ("title", "sent_id"))})
        context = _pairs(row["context"], ("title", "sentences"))
        if not set(titles) <= {title for title, _ in context}:
            raise ValueError("Supporting title is absent from this question's context")
        for title, sentences in context:
            # Hotpot context's sentence list represents one Wikipedia paragraph, not many chunks.
            text = " ".join(sentences)
            if (title, text) not in paragraphs:
                index = title_counts.get(title, 0)
                paragraphs[title, text] = Paragraph(f"{title}::{index}", title, text)
                title_counts[title] = index + 1
        questions.append(
            Question(
                row["id"],
                row["question"],
                row["answer"],
                titles,
                "singlehop" if len(titles) <= 1 else "multihop",
            )
        )
    return Corpus(list(paragraphs.values()), questions, "hotpotqa/distractor/validation")


def load_dataset_corpus(
    source: str = "fixture",
    n: int = 150,
    seed: int = 42,
    fallback: bool = True,
) -> Corpus:
    """Sample validation deterministically; a failed download is visibly recorded, never hidden."""
    if n <= 0 or source not in {"fixture", "hotpotqa"}:
        raise ValueError("Require positive n and source fixture|hotpotqa")
    if source == "fixture":
        return load_fixture(n=n, seed=seed)
    from datasets import load_dataset

    try:
        data = load_dataset("hotpotqa/hotpot_qa", "distractor", split="validation")
    except Exception as exc:
        # Hub transport/cache errors vary by installed provider version. Catch only loading;
        # sampling and schema errors below must remain visible rather than become fixture data.
        if not fallback:
            raise
        reason = f"{type(exc).__name__}: {exc}"
        logger.warning("HotpotQA unavailable; loading fixture: %s", reason)
        fixture = load_fixture(n=n, seed=seed)
        return Corpus(fixture.paragraphs, fixture.questions, fixture.origin, reason)
    sample = data.shuffle(seed=seed).select(range(min(n, len(data))))
    return from_hotpot(list(sample))

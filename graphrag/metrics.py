"""SQuAD-style answer scoring and unique supporting-title recall."""

import re
import string
from collections import Counter


def normalize(text: str) -> str:
    """Lowercase, remove punctuation and English articles, collapse whitespace."""
    text = text.lower().translate(str.maketrans("", "", string.punctuation))
    return " ".join(re.sub(r"\b(a|an|the)\b", " ", text).split())


def exact_match(predicted: str, gold: str) -> float:
    """Return one for equal normalized answer phrases, otherwise zero."""
    return float(normalize(predicted) == normalize(gold))


def f1(predicted: str, gold: str) -> float:
    """Compute multiset token F1, including well-defined empty answers."""
    p, g = normalize(predicted).split(), normalize(gold).split()
    if not p or not g:
        return float(p == g)
    overlap = sum((Counter(p) & Counter(g)).values())
    return 2 * overlap / (len(p) + len(g))


def supporting_recall(retrieved: list[str], gold: list[str]) -> float:
    """Fraction of unique gold titles present in retrieved evidence (empty gold = 1)."""
    expected = set(gold)
    return len(expected & set(retrieved)) / len(expected) if expected else 1.0

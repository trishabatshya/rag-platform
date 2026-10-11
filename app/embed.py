"""Normalized 384-dimensional embeddings with deterministic offline fallback."""

import hashlib
import re
from functools import lru_cache

import numpy as np

from app.config import Settings


@lru_cache(maxsize=1)
def _model(name: str):
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(name)


def embed(texts: list[str]) -> np.ndarray:
    """Return normalized float32 embeddings of shape (len(texts), 384)."""
    settings = Settings()
    if not texts:
        return np.empty((0, 384), dtype=np.float32)
    if settings.mode == "real":
        vectors = np.asarray(
            _model(settings.embedding_model).encode(texts, normalize_embeddings=True),
            dtype=np.float32,
        )
        if vectors.shape != (len(texts), 384):
            raise ValueError("Embedding model must produce 384 dimensions")
        return vectors
    vectors = np.zeros((len(texts), 384), dtype=np.float32)
    for row, text in enumerate(texts):
        for token in re.findall(r"\w+", text.casefold()) or ["<empty>"]:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "little") % 384
            vectors[row, index] += 1 if digest[4] & 1 else -1
        norm = np.linalg.norm(vectors[row])
        if norm == 0:
            vectors[row, 0] = 1
        else:
            vectors[row] /= norm
    return vectors

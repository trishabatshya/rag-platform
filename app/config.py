"""Environment-driven configuration; mock mode requires no services."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

# USD per million tokens: illustrative reference prices, not local-model charges.
PRICES: dict[str, tuple[float, float]] = {"small": (0.15, 0.60), "large": (2.50, 10.00)}


@dataclass(frozen=True)
class Settings:
    """Runtime settings, read when instantiated."""

    mode: str = field(default_factory=lambda: os.getenv("RAG_MODE", "mock"))
    small_model: str = field(default_factory=lambda: os.getenv("SMALL_MODEL", "ollama/llama3.2:3b"))
    large_model: str = field(default_factory=lambda: os.getenv("LARGE_MODEL", "ollama/qwen2.5:7b"))
    judge_model: str = field(default_factory=lambda: os.getenv("JUDGE_MODEL", "ollama/qwen2.5:7b"))
    extract_model: str = field(
        default_factory=lambda: os.getenv("EXTRACT_MODEL", "ollama/qwen2.5:7b")
    )
    ollama_api_base: str = field(
        default_factory=lambda: os.getenv("OLLAMA_API_BASE", "http://localhost:11434")
    )
    qdrant_url: str = field(
        default_factory=lambda: os.getenv("QDRANT_URL", "http://localhost:6333")
    )
    database_url: str = field(
        default_factory=lambda: os.getenv(
            "DATABASE_URL", "postgresql+psycopg://rag:devpassword@localhost:5432/rag"
        )
    )
    embedding_model: str = field(
        default_factory=lambda: os.getenv(
            "EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
        )
    )
    docs_dir: Path = field(
        default_factory=lambda: Path(os.getenv("RAG_DOCS_DIR", str(ROOT / "data" / "docs_sample")))
    )
    state_db: Path = field(
        default_factory=lambda: Path(
            os.getenv("RAG_STATE_DB", str(ROOT / "data" / "runtime" / "state.db"))
        )
    )
    seed_dir: Path = field(
        default_factory=lambda: Path(os.getenv("RAG_SEED_DIR", str(ROOT / "data" / "seed")))
    )
    audit_db: Path = field(
        default_factory=lambda: Path(
            os.getenv("RAG_AUDIT_DB", str(ROOT / "data" / "runtime" / "audit.db"))
        )
    )
    jwt_secret: str = field(default_factory=lambda: os.getenv("JWT_SECRET", ""))
    jwt_ttl_seconds: int = field(default_factory=lambda: int(os.getenv("JWT_TTL_SECONDS", "3600")))

    def __post_init__(self) -> None:
        if self.mode not in {"mock", "real"}:
            raise ValueError("RAG_MODE must be mock or real")
        if self.jwt_ttl_seconds <= 0:
            raise ValueError("JWT_TTL_SECONDS must be positive")


def compute_cost(model: str, in_tokens: int, out_tokens: int) -> float:
    """Estimate USD at reference prices; reject models without a configured tier."""
    settings = Settings()
    if model == settings.small_model:
        tier = "small"
    elif model in {settings.large_model, settings.judge_model, settings.extract_model}:
        tier = "large"
    else:
        raise ValueError(f"No reference price tier configured for model: {model}")
    input_price, output_price = PRICES[tier]
    return (in_tokens * input_price + out_tokens * output_price) / 1_000_000

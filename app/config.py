"""Environment-driven configuration; mock mode requires no services."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

# USD per million tokens, standard GPT-4o-mini/GPT-4o reference tiers; no local charges.
# Sources: https://developers.openai.com/api/docs/models/gpt-4o-mini and /gpt-4o.
# Verified 2026-10-12. Rates can be overridden for a different reference comparison.
PRICES: dict[str, tuple[float, float]] = {
    "small": (
        float(os.getenv("REFERENCE_SMALL_INPUT", "0.15")),
        float(os.getenv("REFERENCE_SMALL_OUTPUT", "0.60")),
    ),
    "large": (
        float(os.getenv("REFERENCE_LARGE_INPUT", "2.50")),
        float(os.getenv("REFERENCE_LARGE_OUTPUT", "10.00")),
    ),
}


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
    requests_db: Path = field(
        default_factory=lambda: Path(
            os.getenv("RAG_REQUESTS_DB", str(ROOT / "data" / "runtime" / "requests.db"))
        )
    )
    cache_threshold: float = field(
        default_factory=lambda: float(os.getenv("CACHE_THRESHOLD", "0.96"))
    )
    cache_ttl: float = field(default_factory=lambda: float(os.getenv("CACHE_TTL_SECONDS", "600")))
    cache_guard: bool = field(
        default_factory=lambda: os.getenv("CACHE_GUARD", "true").lower() == "true"
    )
    router_mode: str = field(default_factory=lambda: os.getenv("ROUTER_MODE", "rule"))
    escalate_no_citation: bool = field(
        default_factory=lambda: os.getenv("ESCALATE_NO_CITATION", "false").lower() == "true"
    )
    retrieval_threshold: float = field(
        default_factory=lambda: float(os.getenv("RETRIEVAL_THRESHOLD", "0.20"))
    )
    run_tag: str = field(default_factory=lambda: os.getenv("RUN_TAG", "api"))
    retrieval_mode: str = field(default_factory=lambda: os.getenv("RETRIEVAL_MODE", "vector"))

    def __post_init__(self) -> None:
        if self.mode not in {"mock", "real"}:
            raise ValueError("RAG_MODE must be mock or real")
        if self.jwt_ttl_seconds <= 0:
            raise ValueError("JWT_TTL_SECONDS must be positive")
        if not 0 <= self.cache_threshold <= 1 or self.cache_ttl <= 0:
            raise ValueError("Require CACHE_THRESHOLD in [0,1] and positive CACHE_TTL_SECONDS")
        if self.router_mode not in {"rule", "llm"}:
            raise ValueError("ROUTER_MODE must be rule or llm")
        if self.retrieval_mode not in {"vector", "graph_hybrid"}:
            raise ValueError("RETRIEVAL_MODE must be vector or graph_hybrid")


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

"""Environment-driven configuration; mock mode requires no services."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


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
    database_url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", "sqlite:///rag.db"))
    embedding_model: str = field(
        default_factory=lambda: os.getenv(
            "EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
        )
    )

    def __post_init__(self) -> None:
        if self.mode not in {"mock", "real"}:
            raise ValueError("RAG_MODE must be mock or real")

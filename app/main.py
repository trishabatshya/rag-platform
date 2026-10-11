"""HTTP entry point; query endpoints arrive in the baseline milestone."""

from fastapi import FastAPI

from app.config import Settings

app = FastAPI(title="Northwind RAG")


@app.get("/health")
def health() -> dict[str, str]:
    """Report service health and the active runtime mode."""
    return {"status": "ok", "mode": Settings().mode}

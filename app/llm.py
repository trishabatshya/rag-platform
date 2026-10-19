"""Shared completion interface with lazy real-provider imports."""

import json
import math
import os
import re
from dataclasses import dataclass
from time import perf_counter

from app.config import Settings


@dataclass(frozen=True)
class LLMResult:
    """Completion text, usage and measured elapsed time."""

    text: str
    in_tokens: int
    out_tokens: int
    model: str
    latency_ms: float
    finish_reason: str | None = None


def complete(
    prompt: str,
    model: str,
    system: str | None = None,
    json_mode: bool = False,
    *,
    timeout: float | None = None,
    max_tokens: int | None = None,
    response_format: dict | None = None,
) -> LLMResult:
    """Complete a prompt at temperature zero; mock answers quote supplied context."""
    start = perf_counter()
    settings = Settings()
    timeout = float(os.getenv("LLM_TIMEOUT_SECONDS", "120")) if timeout is None else timeout
    max_tokens = int(os.getenv("LLM_MAX_TOKENS", "400")) if max_tokens is None else max_tokens
    if not math.isfinite(timeout) or timeout <= 0 or max_tokens <= 0:
        raise ValueError("Completion timeout and max_tokens must be positive finite limits")
    if settings.mode == "mock":
        context = re.search(r"\[1\]\s*(.+?)(?=\n\[\d+\]|\nQuestion:|\Z)", prompt, re.S)
        text = (context.group(1).strip() + " [1]") if context else "I don't know"
        if system and system.startswith("ROUTE_CLASSIFIER:"):
            complex_question = re.search(
                r"\b(compare|why|explain|difference|versus|trade[- ]?off)\b", prompt, re.I
            )
            text = "complex" if complex_question or len(prompt.split()) > 24 else "simple"
        if json_mode:
            text = '{"answer": "I don\'t know"}'
            if "Generate evaluation candidates.\nDOCUMENT:\n" in prompt:
                document = prompt.split("DOCUMENT:\n", 1)[1]
                title, _, body = document.partition("\n")
                text = json.dumps(
                    {
                        "items": [
                            {
                                "question": (
                                    f"What does the {title.lstrip('# ').strip()} document describe?"
                                ),
                                "reference": body.strip().split("\n\n", 1)[0],
                            }
                        ]
                    }
                )
        if system in {"GRAPH_ANSWER", "GRAPH_DECOMPOSE"}:
            from graphrag.mock_llm import graph_completion

            text = graph_completion(prompt, system)
        return LLMResult(
            text,
            max(1, len(prompt.split())),
            max(1, len(text.split())),
            model,
            (perf_counter() - start) * 1000,
        )
    from litellm import completion

    messages = [{"role": "user", "content": prompt}]
    if system:
        messages.insert(0, {"role": "system", "content": system})
    kwargs = {"response_format": {"type": "json_object"}} if json_mode else {}
    if response_format is not None:
        kwargs["response_format"] = response_format
    kwargs.update(timeout=timeout, max_tokens=max_tokens, num_retries=0)
    if model.startswith("ollama/"):
        kwargs["api_base"] = settings.ollama_api_base
    response = completion(model=model, messages=messages, temperature=0, **kwargs)
    return LLMResult(
        response.choices[0].message.content or "",
        response.usage.prompt_tokens,
        response.usage.completion_tokens,
        model,
        (perf_counter() - start) * 1000,
        getattr(response.choices[0], "finish_reason", None),
    )

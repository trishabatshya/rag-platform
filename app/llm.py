"""Shared completion interface with lazy real-provider imports."""

import json
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


def complete(
    prompt: str, model: str, system: str | None = None, json_mode: bool = False
) -> LLMResult:
    """Complete a prompt at temperature zero; mock answers quote supplied context."""
    start = perf_counter()
    settings = Settings()
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
    if model.startswith("ollama/"):
        kwargs["api_base"] = settings.ollama_api_base
    response = completion(model=model, messages=messages, temperature=0, **kwargs)
    return LLMResult(
        response.choices[0].message.content or "",
        response.usage.prompt_tokens,
        response.usage.completion_tokens,
        model,
        (perf_counter() - start) * 1000,
    )

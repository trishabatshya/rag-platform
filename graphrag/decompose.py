"""Validated sequential LLM decomposition, with previous-answer substitution and usage totals."""

import json
import logging
import re
from time import perf_counter

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.contracts import RAGResult
from app.llm import complete
from graphrag.retrieve import GraphPipeline

logger = logging.getLogger(__name__)


class Plan(BaseModel):
    """One to four steps; placeholders can reference only already-completed answers."""

    model_config = ConfigDict(extra="forbid")
    steps: list[str] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def check_steps(self) -> "Plan":
        for index, step in enumerate(self.steps):
            placeholders = re.findall(r"\{([^{}]*)\}", step)
            if not step.strip() or any(
                not re.fullmatch(r"answer\d+", p) or int(p[6:]) >= index for p in placeholders
            ):
                raise ValueError("Steps may reference only prior answers as {answer0}, etc.")
        return self


def answer_decomposed(
    question: str, pipeline: GraphPipeline, model: str | None = None
) -> RAGResult:
    """Plan and answer each step; aggregate evidence/usage without consulting evaluation labels."""
    start = perf_counter()
    model = model or pipeline.settings.large_model
    response = complete(
        json.dumps(
            {
                "question": question,
                "instruction": "Split into sequential single-hop questions. "
                "Return JSON {steps: [strings]}. "
                "Use {answer0}, {answer1} etc. to substitute prior answers. "
                "Return one step for single-hop. Maximum four. Final step answers original.",
                "schema": Plan.model_json_schema(),
            }
        ),
        model,
        system="GRAPH_DECOMPOSE",
        json_mode=True,
    )
    try:
        plan = Plan.model_validate_json(response.text)
    except ValidationError:
        logger.warning("Invalid decomposition; falling back to original question")
        plan = Plan(steps=[question])
    answers, chunks = [], {}
    inputs, outputs = response.in_tokens, response.out_tokens
    result = None
    for step in plan.steps:
        substituted = re.sub(r"\{answer(\d+)\}", lambda m: answers[int(m[1])], step)
        result = pipeline.answer(substituted, system="vector", model=model)
        answers.append(result["answer"])
        inputs += result["in_tokens"]
        outputs += result["out_tokens"]
        chunks.update({c["id"]: c for c in result["chunks"]})
        if result["answer"].casefold() == "i don't know":
            break  # Do not turn an unsupported intermediate answer into a guessed next query.
    assert result is not None
    return {
        **result,
        "sources": sorted({c["source"] for c in chunks.values()}),
        "chunks": list(chunks.values()),
        "in_tokens": inputs,
        "out_tokens": outputs,
        "latency_ms": (perf_counter() - start) * 1000,
    }

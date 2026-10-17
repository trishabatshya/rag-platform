"""Authenticated cache -> ACL retrieval -> route -> generate/escalate -> log orchestration."""

import logging
from dataclasses import dataclass
from functools import lru_cache
from time import perf_counter
from uuid import uuid4

from app.cache import SemanticCache, normalize_query
from app.config import Settings, compute_cost
from app.contracts import CurrentUser, RAGResult
from app.embed import embed
from app.logging_db import RequestEvent, RequestStore, create_request_store
from app.rag import generate_answer
from app.router import RouteDecision, escalation_reasons, llm_route, rule_route
from app.secure_rag import SecureRAGEngine, get_secure_engine


@dataclass(frozen=True)
class ServiceResult:
    """Public response and internal measured route/cost metadata."""

    response: RAGResult
    request_id: str
    route: str
    cache_hit: bool
    escalated: bool
    cost: float
    escalation_reasons: tuple[str, ...] = ()


class RAGService:
    """Serve verified callers with identity-isolated caching and full call accounting."""

    def __init__(
        self,
        engine: SecureRAGEngine,
        cache: SemanticCache,
        requests: RequestStore,
        *,
        cache_enabled: bool = True,
        routing_enabled: bool = True,
        router_mode: str | None = None,
        escalate_no_citation: bool | None = None,
    ) -> None:
        self.engine, self.cache, self.requests = engine, cache, requests
        self.cache_enabled, self.routing_enabled = cache_enabled, routing_enabled
        self.router_mode = router_mode or Settings().router_mode
        self.escalate_no_citation = (
            Settings().escalate_no_citation
            if escalate_no_citation is None
            else escalate_no_citation
        )

    def ask(
        self, question: str, user: CurrentUser | None, *, run_tag: str | None = None
    ) -> ServiceResult:
        """Answer from verified identity; log all returned call usage, never cache exceptions."""
        if user is None:
            raise PermissionError("Verified identity required before cache lookup")
        question = question.strip()
        if not question:
            raise ValueError("Question must not be empty")
        settings, request_id, start = Settings(), str(uuid4()), perf_counter()
        route, model = "complex", settings.large_model
        cache_hit = escalated = stored = False
        in_tokens = out_tokens = 0
        cost = 0.0
        reasons = ()
        try:
            vector = embed([normalize_query(question)])[0].tolist()
            with self.engine.state.access_lock:
                version, epoch = self.engine.state.version, self.engine.state.cache_epoch
                hit = self.cache.lookup(question, user, vector) if self.cache_enabled else None
                if hit is not None and self.engine.validate_cached_evidence(
                    question, user, hit.response, vector, request_id
                ):
                    response = hit.response
                    response["latency_ms"] = (perf_counter() - start) * 1000
                    self.requests.record(
                        RequestEvent(
                            request_id,
                            user.tenant_id,
                            question,
                            response["model"],
                            "cache",
                            True,
                            False,
                            0,
                            0,
                            0.0,
                            response["latency_ms"],
                            run_tag or settings.run_tag,
                            settings.mode.upper(),
                        )
                    )
                    return ServiceResult(response, request_id, "cache", True, False, 0.0)
            decision = (
                llm_route(question) if self.routing_enabled and self.router_mode == "llm" else None
            )
            if decision:
                in_tokens, out_tokens, cost = decision.in_tokens, decision.out_tokens, decision.cost

            def select_model(chunks: list) -> str:
                nonlocal decision, route, model
                if not self.routing_enabled:
                    decision = RouteDecision("complex", "baseline_always_large")
                elif decision is None:
                    decision = rule_route(question, chunks)
                route = decision.route
                model = settings.small_model if route == "simple" else settings.large_model
                return model

            chunks = self.engine.retrieve(
                question, user, select_model, vector=vector, request_id=request_id
            )
            response = generate_answer(question, model, chunks, start)
            in_tokens += response["in_tokens"]
            out_tokens += response["out_tokens"]
            cost += compute_cost(model, response["in_tokens"], response["out_tokens"])
            if route == "simple":
                reasons = escalation_reasons(
                    response, chunks, escalate_no_citation=self.escalate_no_citation
                )
            if reasons:
                escalated = True
                model = settings.large_model
                self.engine.audit.append(
                    request_id,
                    user,
                    question,
                    [chunk["id"] for chunk in chunks],
                    [chunk["doc_id"] for chunk in chunks],
                    model,
                    outcome="escalation",
                )
                response = generate_answer(question, model, chunks, start)
                in_tokens += response["in_tokens"]
                out_tokens += response["out_tokens"]
                cost += compute_cost(model, response["in_tokens"], response["out_tokens"])
            response["in_tokens"], response["out_tokens"] = in_tokens, out_tokens
            if self.cache_enabled:
                stored = self.cache.store(
                    question, response, user, version=version, epoch=epoch, vector=vector
                )
            response["latency_ms"] = (perf_counter() - start) * 1000
            self.requests.record(
                RequestEvent(
                    request_id,
                    user.tenant_id,
                    question,
                    model,
                    route,
                    cache_hit,
                    escalated,
                    in_tokens,
                    out_tokens,
                    cost,
                    response["latency_ms"],
                    run_tag or settings.run_tag,
                    settings.mode.upper(),
                )
            )
            return ServiceResult(response, request_id, route, cache_hit, escalated, cost, reasons)
        except Exception as error:
            if stored:
                self.cache.discard(question, user)
            try:
                self.requests.record(
                    RequestEvent(
                        request_id,
                        user.tenant_id,
                        question,
                        model,
                        route,
                        False,
                        escalated,
                        in_tokens,
                        out_tokens,
                        cost,
                        (perf_counter() - start) * 1000,
                        run_tag or settings.run_tag,
                        settings.mode.upper(),
                        error=type(error).__name__,
                    )
                )
            except Exception:
                logging.exception("Request error could not be instrumented")
            raise


@lru_cache(maxsize=1)
def get_service() -> RAGService:
    """Bind the API's secure engine, cache collection and request instrumentation."""
    engine = get_secure_engine()
    return RAGService(engine, SemanticCache(engine.client, engine.state), create_request_store())


def close_service() -> None:
    """Close instrumentation without closing the separately owned secure engine."""
    if get_service.cache_info().currsize:
        get_service().requests.close()
        get_service.cache_clear()

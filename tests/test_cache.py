"""Identity isolation, invalidation, guard behavior and never-cache policies."""

from contextlib import closing

import pytest

from app.cache import SemanticCache, entity_number_guard, normalize_query, roles_fingerprint
from app.config import Settings
from app.contracts import Chunk, CurrentUser, RAGResult
from app.corpus_state import CorpusState
from app.vectorstore import create_client


@pytest.fixture
def cache_fixture():
    now = [1000.0]
    state = CorpusState(Settings().state_db)
    with closing(create_client()) as client:
        cache = SemanticCache(client, state, clock=lambda: now[0], guard=False)
        user = CurrentUser("acme.hr", "acme", ("employee", "hr"))
        response = RAGResult(
            answer="14 days [1]",
            sources=["refund.md"],
            chunks=[
                Chunk(
                    id="52caa4a2-8774-4fbb-ab0c-ec85fd3206c7",
                    score=1,
                    text="14 days",
                    source="refund.md",
                    doc_id="acme:refund",
                )
            ],
            model=Settings().small_model,
            in_tokens=10,
            out_tokens=3,
            latency_ms=1,
        )
        yield cache, state, now, user, response


def insert(fixture, question="How long is the EU refund window?"):
    cache, state, _, user, response = fixture
    assert cache.store(question, response, user, version=state.version, epoch=state.cache_epoch)
    return question


def test_cache_hit_zero_new_tokens_and_clearing(cache_fixture):
    cache, _, _, user, _ = cache_fixture
    question = insert(cache_fixture)
    hit = cache.lookup(question, user)
    assert hit.response["in_tokens"] == hit.response["out_tokens"] == 0
    assert hit.response["answer"] == "14 days [1]"
    cache.clear()
    assert cache.lookup(question, user) is None


@pytest.mark.parametrize(
    "identity",
    [
        CurrentUser("acme.hr", "globex", ("employee", "hr")),
        CurrentUser("acme.hr", "acme", ("employee",)),
        CurrentUser("acme.other_hr", "acme", ("employee", "hr")),
    ],
)
def test_different_tenant_role_or_user_never_hits(cache_fixture, identity):
    assert cache_fixture[0].lookup(insert(cache_fixture), identity) is None


def test_role_order_is_stable(cache_fixture):
    cache, _, _, user, _ = cache_fixture
    question = insert(cache_fixture)
    reordered = CurrentUser(user.user_id, user.tenant_id, ("hr", "employee", "hr"))
    assert roles_fingerprint(user) == roles_fingerprint(reordered)
    assert cache.lookup(question, reordered) is not None


def test_version_invalidation(cache_fixture):
    cache, state, _, user, _ = cache_fixture
    question = insert(cache_fixture)
    with state.connection() as connection:
        connection.execute("UPDATE corpus_state SET version=version+1 WHERE id=1")
    assert cache.lookup(question, user) is None


def test_epoch_invalidation(cache_fixture):
    cache, state, _, user, _ = cache_fixture
    question = insert(cache_fixture)
    state.bump_cache_epoch()
    assert cache.lookup(question, user) is None


def test_ttl_boundary_and_future_timestamps(cache_fixture):
    cache, _, now, user, _ = cache_fixture
    question = insert(cache_fixture)
    now[0] += cache.ttl - 0.01
    assert cache.lookup(question, user) is not None
    now[0] += 0.01
    assert cache.lookup(question, user) is None
    now[0] = 999.0
    assert cache.lookup(question, user) is None


@pytest.mark.parametrize(
    "answer", ["", " ", "I don't know", "I don’t know", "I don't know based on the context."]
)
def test_uncacheable_answers(cache_fixture, answer):
    cache, state, _, user, response = cache_fixture
    response = {**response, "answer": answer}
    assert not cache.store(
        "question", response, user, version=state.version, epoch=state.cache_epoch
    )
    assert cache.client.count(cache.collection).count == 0


def test_anonymous_lookup_does_not_query_vectors(cache_fixture, monkeypatch):
    cache, state, _, _, response = cache_fixture

    def forbidden(*args, **kwargs):
        raise AssertionError("Anonymous identity must not search cache")

    monkeypatch.setattr(cache.client, "query_points", forbidden)
    assert cache.lookup("question", None) is None
    assert not cache.store(
        "question", response, None, version=state.version, epoch=state.cache_epoch
    )


def test_generation_snapshot_change_prevents_store(cache_fixture):
    cache, state, _, user, response = cache_fixture
    epoch = state.cache_epoch
    state.bump_cache_epoch()
    assert not cache.store("question", response, user, version=state.version, epoch=epoch)


@pytest.mark.parametrize(
    "first,second,passes",
    [
        ("How much is Pro?", "What does Pro cost?", True),
        ("How much is Pro?", "How much is Team?", False),
        ("What is the EU refund window?", "What is the US refund window?", False),
        ("Can I add 5 seats?", "Can I add 25 seats?", False),
        ("What is 99.9 percent uptime?", "What is 99.0 percent uptime?", False),
        ("How do I enable webhooks?", "How do I disable webhooks?", True),
    ],
)
def test_entity_number_guard_and_its_direction_limit(first, second, passes):
    assert entity_number_guard(first, second) is passes


def test_normalization_preserves_word_boundaries():
    assert normalize_query("  HELLO, world! ") == "hello world"
    assert normalize_query("EU/US API-keys") == "eu us api keys"


def test_guard_rejects_similar_number_flip(cache_fixture):
    cache, state, _, user, response = cache_fixture
    cache.threshold, cache.guard = 0.5, True
    first = "Can I add 5 member seats to Pro?"
    assert cache.store(first, response, user, version=state.version, epoch=state.cache_epoch)
    assert cache.lookup("Can I add 25 member seats to Pro?", user) is None


def test_cache_scope_is_filtered_inside_query(cache_fixture, monkeypatch):
    cache, _, _, user, _ = cache_fixture
    question = insert(cache_fixture)
    original = cache.client.query_points
    observed = {}

    def record(*args, **kwargs):
        observed.update(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(cache.client, "query_points", record)
    cache.lookup(question, user)
    fields = {condition.key for condition in observed["query_filter"].must}
    assert fields == {"tenant_id", "user_id", "roles_fingerprint", "version", "epoch", "ts"}


def test_entries_are_independent_response_copies(cache_fixture):
    cache, _, _, user, _ = cache_fixture
    question = insert(cache_fixture)
    first = cache.lookup(question, user)
    first.response["answer"] = "modified by caller"
    assert cache.lookup(question, user).response["answer"] == "14 days [1]"

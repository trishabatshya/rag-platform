# Repository instructions

1. Never fabricate measurements. Results must come from scripts run in this session;
   pending real measurements are `NOT YET RUN`. Mock measurements are not results.
2. Implement M0 through M5 in order. After each, run tests, fix failures, update
   PROGRESS.md, and commit. Do not advance with failing tests.
3. All unit tests and CI run offline in `RAG_MODE=mock`: deterministic 384-dimensional
   hash embeddings, deterministic LLM, in-memory Qdrant, SQLite. Real mode uses local
   models through LiteLLM, sentence-transformers, Qdrant, Postgres and Neo4j.
4. Default to free open-source tools and configurable local Ollama model names.
5. Inspect installed APIs; pin versions only after installation and passing checks.
6. Never commit secrets; use .env.example and ignore .env.
7. Make reasonable decisions without questions; record trade-offs in DECISIONS.md.
8. Derive identity exclusively from verified JWTs. Pre-filter vector retrieval,
   recheck ACLs in Python, audit every retrieval (including cache hits).
9. Use Python 3.11, type hints, public docstrings, small modules, ruff and pytest.
   No dead code or TODO feature stubs. Use pathlib and shell-free subprocess calls.

## Commands

PowerShell, from the repository root:

```powershell
py -3.11 -m venv .venv311
.\.venv311\Scripts\Activate.ps1
$env:RAG_MODE="mock"
python tasks.py install
python tasks.py lint
python tasks.py test
python tasks.py eval
python tasks.py bench-acl
python tasks.py bench-cache
python tasks.py bench-graph
python tasks.py report
```

If activation is blocked, use `.\.venv311\Scripts\python.exe tasks.py test`.
The Makefile delegates the same targets to tasks.py. On POSIX, use
`RAG_MODE=mock python tasks.py test`. Test/eval/bench features are delivered in
milestone order; consult PROGRESS.md before invoking later targets.

## Optional real-mode dependencies

The default `python tasks.py install` installs the offline stack from requirements.txt.
For real embeddings, reranking and LiteLLM completions, use the same Python environment:

```powershell
python -m pip install -r requirements-real.txt
python -m pip check
$env:RAG_MODE="real"
```

The real requirements include the base file; do not install unpinned model libraries
over it. Keep shared huggingface-hub/filelock pins compatible with both stacks. Without
activation, use `.\.venv311\Scripts\python.exe -m pip install -r requirements-real.txt`.
POSIX uses the same pip command and `export RAG_MODE=real`. Installing libraries does not
download model weights or start Ollama/database services. Mock tests must remain offline
and import optional model libraries lazily. Missing sentence-transformers must produce
an actionable installation message; errors in its transitive dependencies must retain
their original diagnostic rather than be mislabeled as the package being absent.
NEO4J_URI in .env also opts into the live integration test. To validate just the offline
suite without running Neo4j, use `python tasks.py test -m "not integration" -q`; report
external connection failures separately rather than claiming the live test passed.

## Layout

- app/: config, embeddings, completions, vector store, baseline RAG, auth, ACL,
  secure_rag, append-only audit, semantic cache, router, service and request logging.
- graphrag/: dataset, schema, extraction, resolution, storage and retrieval.
- data/: docs_sample, seed, eval.jsonl, cache_pairs, router_labels.jsonl, graph_fixture.
- scripts/: corpus/data helpers and report generator.
- eval/: evaluation and benchmark runners; results/ holds generated outputs.
- tests/: offline contracts and regression suites.
- docs/: interview study notes.
- tasks.py / Makefile: portable tasks; Dockerfile / docker-compose.yml: deployment.
- migrations/: PostgreSQL append-only audit enforcement.

Shared contracts: `embed(list[str]) -> np.ndarray` (float32, normalized, n x 384),
`complete(prompt, model, system=None, json_mode=False) -> LLMResult`.
The baseline `rag_pipeline(question, model, user=None) -> dict` returns
answer, sources, chunks (id, score, text, source, doc_id), model, in_tokens,
out_tokens and latency_ms. Keep these interfaces stable as later milestones land.

## M1 commands and boundaries

```powershell
$env:RAG_MODE="mock"
python tasks.py ingest
python tasks.py eval --tag baseline --limit 45
python tasks.py run
python -m scripts.fetch_corpus urls.txt --output-dir data/docs
python -m scripts.gen_eval --docs data/docs_sample --output data/eval_candidates.jsonl
python -m eval.judge_check eval/results/baseline_TIMESTAMP.csv --output eval/results/judge_review.csv
python -m eval.judge_check eval/results/judge_review.csv --agreement
```

Use an actual generated filename in place of baseline_TIMESTAMP.csv. Mock service/eval
processes reload RAG_DOCS_DIR because Qdrant's in-memory index is process-local.
RAG_STATE_DB persists corpus versions and ingestion manifests; use pathlib for paths,
UTF-8 for text and newline="" for CSV. Close SQLite and vector handles on every exit.
Human-review all candidates before removing needs_review; never silently use drafts
in the reviewed evaluation. Baseline evaluation is isolated in baseline_chunks;
the HTTP /ask endpoint requires verified JWTs and uses ACL-protected chunks.

## M2 commands and security boundaries

```powershell
$env:RAG_MODE="mock"
python tasks.py test tests/test_leakage.py
python tasks.py bench-acl --queries 200
python tasks.py ingest --corpus seed
python -m scripts.make_seed
```

Default ingestion loads both corpora; --corpus baseline selects the public evaluator.
Seed regeneration creates fresh random PBKDF2 salts for demo-only users. No real secret
may be committed. JWT_SECRET may be empty in mock mode (random process-local key);
real authentication requires >=32 bytes, e.g. PowerShell:
`$env:JWT_SECRET = python -c "import secrets; print(secrets.token_urlsafe(48))"`.
Use the same key in all workers. Mock audit always uses RAG_AUDIT_DB (SQLite);
real audit requires a PostgreSQL DATABASE_URL and installs migrations automatically.

Do not add an API option to disable filtering or use request-body identity. The Qdrant
filter must require tenant equality and at least one role/user grant. Public labels do
not grant cross-tenant access; admin is not a universal bypass. Validate metadata before
any ACL write; bare documents must never enter the ACL collection. Audit before generation,
including empty/failed retrievals, and fail closed if audit cannot commit. Admin access
queries and mutations must remain tenant-scoped. ACL changes bump the persisted epoch
before mutation. M3 implements cache-hit audit and invalidation to retain these guarantees.

The leakage oracle must read seed grants directly rather than production ACL functions.
Test raw query results, response chunks and answer markers, plus positive access and
negative controls. Benchmark unfiltered calls belong only in a disposable collection
and measure raw operations, not authenticated end-to-end latency. Mock metrics must never
be promoted into README real-result tables.

## M3 commands and cache/routing rules

```powershell
$env:RAG_MODE="mock"
python tasks.py test tests/test_cache.py tests/test_router.py tests/test_service.py tests/test_cache_leakage.py
python tasks.py bench-cache
python -m eval.bench_cache_router --sweep
python -m eval.bench_cache_router --router
python -m eval.bench_cache_router --compare --repeat-ratio 0.40
python tasks.py dashboard
```

The runner's bench-cache target executes all three experiments. RAG_REQUESTS_DB points
to the mock SQLite measurement log; real mode requires PostgreSQL. Configure
CACHE_THRESHOLD, CACHE_TTL_SECONDS, CACHE_GUARD, ROUTER_MODE=rule|llm,
RETRIEVAL_THRESHOLD and RUN_TAG using PowerShell `$env:NAME="value"` syntax.

Cache scope requires tenant, sorted-role fingerprint and verified user ID: roles alone
cannot isolate explicit-user grants. All cache hits must match version, epoch and TTL,
revalidate current evidence with the ACL pre-filter/post-check, and commit an audit entry.
Do not cache empty/abstaining/uncited answers or exceptions, or an older snapshot after
corpus/ACL changes during generation. Keep the cache snapshot checks under the same
single-worker state lock as admin ACL updates. Cache hits have zero new LLM tokens.

Log and sum every completed generation call and optional classifier usage at its own
reference tier, including escalation. Unknown API quality stays NULL; only attach
measured judge results. Defaults use published reference tiers cited in README, with
REFERENCE_SMALL_INPUT/OUTPUT and REFERENCE_LARGE_INPUT/OUTPUT overrides; local models
still have no paid API charge. Rule selection runs after post-check via a pure callback
before audit; the optional LLM classifier sees only the question before retrieval.

Pair/router fixtures are tuning data, not production evidence. Benchmarks use disposable
collections and the same seeded workload across systems. Every output records runtime
mode and repeat ratio, and mock summary numbers never enter README's real-results table.
The dashboard is a local operator tool; keep unknown quality visibly unknown and mock
data separate from real data. Streamlit tests use its installed headless AppTest API.

## M4 commands and graph boundaries

```powershell
$env:RAG_MODE="mock"
python tasks.py bench-graph --dataset fixture
$env:GRAPH_EXTRACT_CACHE="data/runtime/graph_extract"
python -m scripts.failure_analysis eval/results/project3_TIMESTAMP.csv
```

Use an actual generated CSV filename. GraphRAG is standalone and public-only; no tenant
ACLs apply. Never ingest protected tenant documents
into this graph. Gold answers/supporting titles are evaluation-only; mock extraction may
use paragraph annotations, but retrieval/generation must never consult question labels.
Mock completions operate on supplied evidence, not fixture answers. All outputs must
record mode and actual dataset origin; fallback does not become a real HotpotQA result.

Extraction means initial attempt plus at most two retries, strict schema validation and logged
skip on final failure. EXTRACT_TIMEOUT_SECONDS defaults to 90 per call; disable provider
retries and abort after three consecutive timeout/connection failures. Use json_schema
response_format with the fixed Extraction enums, at most 8 entities/8 relations. Repair
string entities, empty names and entity aliases before strict validation; unknown entity
types become OTHER, unknown relation types become RELATED_TO. Drop dangling relations
after repair. Keep the schema type lists fixed and document predicate-semantic loss.
Record kept/dropped relations and fully failed chunks. Persist successes only.
EXTRACT_MAX_TOKENS defaults to 1000 (PowerShell `$env:EXTRACT_MAX_TOKENS="1000"`).
Count fresh attempted/clean/repaired/failed chunks and repair occurrences separately
from cache hits. Console failures must be short; append full errors/raw responses to
extraction_failures.log, with test logs isolated in temporary directories.
Skip truncated JSON for that chunk only, preserving vector evidence and never caching
partial results. Include skipped_chunk_details/skipped_reasons in indexing summaries
and mode-labeled skipped_chunks.txt, including on outage abort; mark aborted summaries
incomplete without a benchmark CSV.
All complete() calls must apply LLM_TIMEOUT_SECONDS=120 and LLM_MAX_TOKENS=400
when not explicitly overridden; always pass finite limits and num_retries=0 to LiteLLM.
Graph benchmark defaults to --systems vector,graph_hybrid; decomposition is opt-in.
Catch per-question generation exceptions, checkpoint terminal successes/failures
immediately, and resume only matching corpus/mode/model/config checkpoints. Count
completed/failed/timed_out and invalid_decomposition per system; timeout counts are
a subset of failures. Failed partial usage is unknown, never fabricated as zero.
Cache keys isolate mode/model/text/schema
and mock annotations. Sum every completed extraction call, including invalid JSON; cache
hits add zero new tokens/cost. Failed extraction preserves vector-only evidence. Indexing
cost excludes embeddings, reranking, database and local compute charges; label that scope.

Keep entities typed throughout resolution/linking/traversal. Review `merge_groups.txt`:
Use normalized plain ratio >=92, never token_set_ratio. Block strict token subsets,
including optional embedding matches, except PERSON two-token first/last matches with
inserted middle names. Preserve type separation and complete-link grouping. Record
canonical-assignment merge_counts by reason in indexing summaries and merge reports.
--fresh-extraction must bypass cache reads without overwriting first-fill provenance.
Always include first_fill_extraction time/tokens/cost separately from current-run usage;
legacy entries without measurements are unknown/null, never zero. Persist successful
first-fill measurements, deduplicate cache keys and fingerprint resolved graph evidence
for checkpoint compatibility. Do not cache failed extractions.
Nickname aliases and the PERSON exception can still merge distinct people. Optional embedding resolution
is off by default. Every graph relation retains supporting chunk_id; prompt triples must
come only from selected evidence. Keep bounded two-hop expansion, top15 vectors, top6
reranked evidence and <=10 prompt triples. Planner usage counts toward decomposition.

Neo4j benchmark nodes are run-namespaced; remove only the owned namespace and close all
handles, including on failure. Shared indexes/constraints remain. The vector overfetch /
namespace fallback is not ACL enforcement. Mock uses NetworkX, not a fake live result.
External tests are `integration` and skip unless NEO4J_URI is explicitly set, e.g.
PowerShell `$env:NEO4J_URI="bolt://localhost:7687"`. An opted-in missing service must fail.
The test embeddings are deterministic; live integration tests need only Neo4j, not models.

Live Qdrant leakage is a separate integration suite: set PowerShell
`$env:RUN_QDRANT_INTEGRATION="1"` and run
`python tasks.py test tests/test_leakage_qdrant_integration.py -m integration -q`.
It explicitly uses http://localhost:6333 despite mock model mode, a UUID-owned disposable
collection, SQLite audit, and the same 600 case assertions/negative controls as the
in-memory suite. Never describe it as real-model/Postgres/cache or load-test coverage.
The original test_leakage.py remains in-memory even under a real shell configuration;
module fixture setup must also force mock embeddings before function fixtures execute.
Do not silently skip an opted-in unavailable Qdrant or fall back to memory. Delete only
the owned collection and preserve application collections. Report server/client versions
and compatibility warnings with any live-server claim.

## M5 integration and reporting

```powershell
$env:RAG_MODE="mock"
$env:RETRIEVAL_MODE="graph_hybrid"
python -m graphrag.pipeline "Where was the director of Amber Signal born?"
$env:RETRIEVAL_MODE="vector"
python tasks.py report
python tasks.py lint
python tasks.py test -q
docker compose config --quiet
```

RETRIEVAL_MODE applies only to the standalone public multi-hop entry point. `/ask` always
uses JWT identity, the protected vector collection, ACL-scoped cache and immutable audit.
Do not use a mode switch to bypass those controls. The public graph callable rejects a
tenant identity before indexing. Close its owned store before changing source/config and
on every CLI exit. GraphRAG output has the shared response fields but a short answer;
tenant answers retain citations. No public graph response enters the tenant cache.

Report selection is separate for REAL and MOCK, ordered by file modification time then
name. Publish real numeric metrics only from explicitly labeled completed CSVs. Pair
Project 1 by matching run tags/workloads; skip unpaired comparisons. Require matching
CSV/mode/corpus for graph indexing JSON. Keep archived summaries so a newer mock run
cannot erase real indexing provenance. Unknown/mixed modes or malformed selected data
must fail before rewriting README. Preserve all text outside the one RESULTS marker pair.
Mock status is always `MOCK (not a result)`; absent real measurements are `NOT YET RUN`.
Synthetic REAL artifacts used in tests belong only in temporary directories and must
never enter the repository's report/results. Preserve human reviews before rerunning.

Real model install/download and service startup remain human-run until tools/models are
available. Inspect and pin compatible installed APIs before publishing real numbers; do
not present configured adapters or Compose validation as live provider/database evidence.

## Project 1 benchmark follow-up

Sweep CACHE_THRESHOLD from 0.85 through 0.99; preserve true-paraphrase hit rate
and false-hit count at every threshold. Default 0.96 was selected from a full
real guarded tuning sweep; mock numbers must never retune real deployments.
PowerShell overrides: `$env:CACHE_THRESHOLD="0.96"` and
`$env:ESCALATE_NO_CITATION="false"` (default; `"true"` enables citation escalation).
Compare both citation policies on the identical workload, with independently
cleared caches. Quality is reference_in_answer; retain the LLM judge as secondary.
Escalation reasons come from the original small answer; divide escalations by
simple-routed requests, and route counts by all requests. Reasons can overlap.

# Progress

- [x] M0: Scaffold (mock acceptance passed; real-provider validation pending)
- [x] M1: Baseline RAG and evaluation (mock acceptance passed)
- [x] M2: Permission-aware multi-tenant RAG (mock acceptance passed)
- [x] M3: Semantic cache and routing (mock acceptance passed)
- [x] M4: GraphRAG (mock acceptance passed; live Neo4j/models pending)
- [x] M5: Integration and polish (offline acceptance passed; real runs pending)

M0: Installed and pinned mock dependencies under Python 3.11.9 on Windows.
`python tasks.py install`, `python tasks.py lint`, and `python tasks.py test`
passed (six tests); `docker compose config --quiet` passed. Inspected installed
Qdrant constructor/query/collection APIs and adapted explicit client closing.
Added the portable runner, Makefile, containers, Windows/Linux CI, shared contracts,
documentation and milestone directories. Real adapters exist but their optional
sentence-transformers/LiteLLM installation and API verification remain pending:
the large download was stopped before completion. Ollama is absent and Docker's
daemon check did not return; no containers, model calls or benchmarks were run.
Before any real-mode evaluation,
install and inspect provider dependencies, pin them, and validate both adapters.

M1: Added 20 fictional Northwind Cloud Markdown documents and 45 hand-written
evaluation items (40 answerable, five unanswerable), paragraph-aware 400-word
chunking with 60-word overlap, stable chunk IDs, stale-chunk cleanup and a persisted
SQLite corpus version. Implemented top-five retrieval, context-only prompts,
parsed citations, question-only POST /ask, corpus fetch and review-flagged candidate
helpers, mock token-F1/real binary judging, human-review sampling/agreement, and
timestamped CSV evaluation with reference-cost and judge-overhead accounting.
On Windows/Python 3.11, `python tasks.py lint` and `python tasks.py test -q` passed
(51 tests); `python tasks.py ingest` ingested all 20 documents and `python tasks.py
eval` evaluated all 45 items, writing
`eval/results/baseline_20261011T150116095389Z.csv` with MOCK labels. The Makefile
delegates these same targets to tasks.py; GNU make itself was not used.
Updated README/AGENTS with PowerShell commands, process-local mock indexing and
human-review instructions. Real provider installation/API verification, actual
Ollama generation, live Qdrant retrieval and public-network downloads remain
unverified; helper failures and successes were tested offline with injected responses.
The existing Starlette/httpx deprecation warning remains non-failing. No mock quality
or cost numbers were copied into README results. M2 is the first unfinished milestone;
work stopped here as requested.

M2: Added committed fixtures for Acme, Globex and Initech (15 PBKDF2-hashed demo
users, 18 ACL documents), strict metadata ingestion into the ACL collection, HS256
JWT login/verification and a protected question-only /ask endpoint. Retrieval applies
tenant AND role/user grants inside Qdrant, rechecks returned payloads, drops/logs violations
and exposes tenant-scoped admin counters. SQLAlchemy audit records commit before generation
(including empty/error retrievals), with SQLite UPDATE/DELETE/REPLACE protections, exact
tenant/date-scoped document access and a PostgreSQL append-only trigger migration.
Admin ACL updates touch all document chunks, wait for completion and bump a persisted
cache_epoch; multi-chunk tests verify the very next query loses revoked access. The
leakage oracle derives forbidden IDs/markers directly from seed grants, checks raw
results and generated/returned text, verifies positive access and audit records across
600 user/query combinations, and includes negative controls that prove disabled defenses
are detected. On Windows/Python 3.11, final lint and all 694 tests passed; dependency
consistency and Compose config checks passed, and the Windows/Linux offline CI YAML
was validated by tests. `python tasks.py bench-acl` measured 200 raw filtered/unfiltered
pairs plus revocation, writing `eval/results/acl_20261011T162358253995Z.csv` with MOCK
labels; baseline evaluation still ran all 45 questions and both corpora ingested.
No mock timing/quality/cost metrics were promoted into README real-results tables.
Live Qdrant payload indexes/filtering, PostgreSQL migration execution, real-model
generation and hosted GitHub Actions remain unverified. Real provider dependency
installation remains pending from M0; existing Starlette/httpx deprecation is non-failing.
README, AGENTS and DECISIONS document PowerShell login/admin commands, demo-only auth,
single-worker/local epoch scope and audit protection limits. M3 is the first unfinished
milestone; work stopped here as requested.

M3: Added request instrumentation with separately computed reference cost for each
completed model call, a tenant/role/user-scoped semantic cache with version/epoch/TTL
checks and optional entity/number guard, rule and small-model routers, escalation, and
the /ask orchestration service. Cache hits revalidate ACL-filtered evidence and commit
cache-hit audit records; generation-time ACL/corpus changes prevent stale cache insertion.
Committed 50 curated paraphrase pairs, 50 near-miss pairs and 100 hand-labeled router
intents. Added threshold sweeps, both-router accuracy and quality/cost trade-off runs,
and identical seeded baseline/optimized replay with configurable repeats, plus a local
Streamlit measurement dashboard. Inspected installed Streamlit 1.65.0 test/chart APIs,
pinned all successfully installed dependencies and verified published reference tiers;
local-model cost remains estimated at reference prices. On Windows/Python 3.11, lint
and all 1353 tests passed, including the existing leakage suite, 600 additional cached
service combinations, TTL/version/epoch invalidation, explicit-user isolation, escalation
accounting, poisoned-evidence rejection and headless dashboard empty/data/filter checks.
`python tasks.py bench-cache` completed the full sweep and 100-label router experiments,
then the default 40%-repeat comparison (75 requests per system), writing MOCK-labeled
CSV files and `eval/results/summary_project1.json`. Comparison CSVs are
`project1_baseline_20261012T050018521260Z.csv` and
`project1_optimized_20261012T050018528161Z.csv`; no mock performance/quality/cost numbers
were copied into README results. Dependency consistency and Compose configuration checks
passed. Live Qdrant/PostgreSQL, real generation/classifier quality, browser interaction,
model/GPU setup and hosted CI remain unverified; real provider dependency setup remains
pending from M0. The existing Starlette/httpx warning is non-failing. README/AGENTS include
PowerShell experiment/dashboard commands and DECISIONS records scope and limitations.
M4 is the first unfinished milestone; work stopped here as requested.

M4: Added a standalone GraphRAG pipeline with vector-only, graph-hybrid and sequential
decomposition systems. Committed an authored fixture of 39 fictional paragraphs,
12 bridge questions, 3 single-hop questions and event distractors, plus a deterministic
regeneration script. Added a seeded HotpotQA distractor validation loader with current
dict/historical pair fields, paragraph deduplication/title-index IDs, and visibly recorded
offline fallback/strict mode. Inspected installed datasets 5.1.0 load/shuffle/select APIs
and a current HotpotQA viewer example; did not download the full dataset. Implemented
SQuAD EM/multiset F1 and unique supporting-title recall with hand-computed tests.

Extraction validates fixed typed Pydantic entities/relations, retries three times after
the initial attempt, logs/skips final graph extraction failure, and persists validated
outputs in a mode/model/text/schema-isolated disk cache. Invalid JSON completions count
toward indexing usage; cache hits add zero new tokens/cost. Mock extraction uses only
paragraph annotations and has zero model calls. Resolution uses type-scoped >=92 fuzzy
matching, explicit Chris/Christopher normalization, longest canonical names, optional
embedding resolution and a human-review merge report. DECISIONS documents tested subset
name/nickname false-merge risks. NetworkX and Neo4j implement the same bounded expansion,
vector and evidence-triple interface. Neo4j adds constraints, a 384-d cosine index and
MERGE loaders; fresh run namespaces prevent cross-run paths and scope cleanup. Real
ANN overfetch/namespace filtering has an owned-vector starvation fallback, not ACLs.
Hybrid links aliases, expands zero to two hops, reranks combined candidates to six chunks
and supplies up to ten selected-evidence triples. Decomposition validates up to four
steps, substitutes previous answers, sums planner/step usage and stops on abstention.
All systems preserve the shared response fields, with public retrieved titles as sources.

On Windows/Python 3.11, `python tasks.py lint` passed and the final full
`python tasks.py test -q` run passed **1401 tests, 1 skipped** in 60.99s. The skip is the
live Neo4j integration test because NEO4J_URI is unset; its real execution was not claimed.
Tests cover typed identity/path bounds, cache reuse/corruption/mode/model/text separation,
retry accounting, gold-label independence, prompt evidence bounds, sequential usage,
driver parameters and spaces/Unicode in Windows paths. The fixture acceptance sanity
check passed: hybrid supporting-title recall >= vector baseline. This is a mock software
check, not a real retrieval result. `python tasks.py bench-graph` completed all 15
questions for all three systems (45 CSV rows), generating
`eval/results/project3_20261012T114644786463Z.csv`, `summary_project3.json`,
`merge_groups.txt` and `failure_analysis_project3.md`, all labeled MOCK (not a result).
The rerun reused all 39 extraction cache entries with zero new extraction tokens/cost.
Failure export included ten of twelve observed vector failures and explicitly zero
available failures for the other fixture systems; no failures or measurements were
invented. README's real measurements remain NOT YET RUN.

Installed/pinned networkx 3.6.1, rapidfuzz 3.14.6, neo4j 6.4.0, datasets 5.1.0 and their
successful transitive dependencies; the initial download timed out and the approved
retry succeeded. Inspected installed driver/NetworkX APIs and official Neo4j vector-index
documentation. Reinstall from requirements.txt, pip check and Compose configuration
validation passed. README/AGENTS document PowerShell graph commands, artifact review,
cache configuration and the standalone public-corpus boundary. Live Neo4j/Cypher/index
behavior, full HotpotQA loading, real extraction/generation/embeddings/cross-encoder
quality, model/GPU setup and hosted Windows/Linux CI remain unverified; optional real
model dependencies from M0 remain pending and Ollama is unavailable. M5 is the first
unfinished milestone; work stopped here as requested.

M5: Completed integration, reporting and documentation. Added validated
RETRIEVAL_MODE=vector|graph_hybrid selection through the standalone public multi-hop
callable/CLI, preserving the shared response fields and rejecting supplied tenant
identity before indexing. The owned graph is reused for a matching configuration and
closed before replacement or CLI exit; responses record actual dataset origin.
Authenticated `/ask` remains on the ACL-protected vector/cache/audit service in both
settings. New HTTP integration regressions verify login, a repeated question's zero-token
cache hit, immutable cache_hit/source-doc audit, administrator revocation and the next
answer's exclusion of revoked evidence, with no public graph invocation. Existing
tenant/role/user cache scope and the independent 600 retrieval + 600 cached-service
leakage combinations/negative controls remain in the final suite.

Implemented `scripts/make_report.py` and the existing tasks.py/Makefile report target.
It selects latest completed REAL and MOCK CSVs independently, validates explicit modes,
pairs Project 1 run tags/workloads, computes measured CSV metrics and reads only matching
GraphRAG indexing JSON provenance. Mixed/missing modes, invalid selected measurements,
mispaired workloads and summary mismatches fail before README is rewritten. Mock checks
show only MOCK (not a result) status/source artifacts; absent real runs remain NOT YET RUN.
Updates preserve text outside the RESULTS markers and are idempotent. Benchmarks now
archive timestamped Project 1/3 JSON summaries alongside fixed latest summaries, retaining
indexing provenance when later runs change mode. Synthetic REAL reporting test fixtures
exist only under pytest temporary paths and were never published as actual measurements.

README now leads with an accurate architecture, pitch and auto-generated results tables,
documents a one-command mock container demo and an alternate host process quickstart,
exact reproduction commands, optional model setup, PowerShell environment syntax, design
decisions, limitations and an honest dashboard screenshot placeholder. Host quickstart
starts database containers only before a host API, avoiding port 8000 conflicts. Added
approximately two-page-per-project interview notes in docs/STUDY_NOTES.md (3078 words)
covering problem, implementation, evidence, trade-offs and improvements. AGENTS and
DECISIONS document the mode boundary, reporting rules and remaining validation limits;
.env.example includes the new standalone retrieval setting and all implemented settings.

On Windows/Python 3.11, final `python tasks.py lint` passed and
`python tasks.py test -q` passed **1423 tests, 1 skipped** in 51.12s. The skip is the
opt-in live Neo4j integration because NEO4J_URI is unset. `make` is unavailable, so the
same targets were run through the Python runner to which the Makefile delegates.
`docker compose config --quiet`, pip check and diff whitespace validation passed.
The actual README report was regenerated and verified idempotent; the standalone
graph_hybrid CLI returned Cedar Bay on the bridge fixture with MOCK labeling and closed
its store. Reviewed configuration/source changes contain no live credentials or keys;
.env/private-key files are not tracked and the local .env does not exist.

Reran all benchmark targets end to end in mock mode in this milestone: baseline evaluation
over all 45 reviewed items; the cache threshold sweep, both-router experiments and 40%
repeat comparison with 75 requests/system; ACL benchmark with 200 paired raw queries and
revocation verification; GraphRAG with all 15 fixture questions across three systems
(45 rows). Actual source artifacts recorded in README are
`baseline_20261013T123347119648Z.csv`,
`project1_baseline_20261013T123357729802Z.csv`,
`project1_optimized_20261013T123357732368Z.csv`,
`acl_20261013T123350396285Z.csv` and `project3_20261013T123348499080Z.csv`.
All outputs are MOCK-labeled and no mock numeric scores were promoted to real results.

Could not verify live Qdrant/Postgres/Neo4j execution, container startup, full HotpotQA
loading, real extraction/generation/classification/embeddings/cross-encoder quality,
GPU/model setup, browser screenshot/use or hosted Windows/Linux CI. Ollama and make are
absent, no local models are configured, and optional real-provider dependencies/API
verification remain pending from M0. Human-run setup/reproduction commands are documented;
no unavailable-tools real runs were attempted. All M0-M5 offline acceptance is complete;
work stopped at M5 as requested.

Post-M5 dependency follow-up (2026-10-16): Added requirements-real.txt including the
base requirements and exact versions of the installed additional model stack:
sentence-transformers 6.1.0, LiteLLM 1.105.1, torch 2.14.1, transformers 5.20.0 and
their additional installed dependencies. Changed shared base pins to filelock 3.32.7
and huggingface-hub 1.33.0 because the earlier 4.x/2.x pins conflict with model-library
bounds. The optional profile installed successfully on Windows/Python 3.11, installing
it again with --no-index succeeded, and pip check found no broken dependencies.
Inspected installed encode/predict/completion APIs, ran LiteLLM's offline mock_response
path, and checked app/embed with a locally constructed SentenceTransformer BoW encoder:
float32, normalized (2,384) vectors without pretrained weights. This resolves library
installation/API inspection pending from M0, not live model inference or quality.

app/embed.py now raises an actionable RuntimeError when sentence_transformers is absent,
including `python -m pip install -r requirements-real.txt`. Transitive missing modules
retain their original diagnostics and mock embeddings do not import optional models.
Three new offline regression cases passed. README quickstart/real setup and AGENTS now
document the profile, PowerShell/POSIX syntax, the default Docker mock-only image and
offline-only testing when NEO4J_URI is configured. DECISIONS records shared-pin rationale.
Lint and diff whitespace checks passed. The full suite reported 1426 passed and one
failed external integration: the configured Neo4j at localhost:7687 refused connections.
No application/unit test failed; no live Neo4j success is claimed. Pretrained model
downloads/inference, live provider calls and cross-platform/GPU checks remain unverified.
The explicit offline command `python tasks.py test -m "not integration" -q` subsequently
passed all 1426 tests, with one external test deselected, in 128.01s.

Judge-reply follow-up (2026-10-16): Added Verdict.raw and the baseline evaluator's
judge_raw CSV column, preserving completion text before strip/uppercase parsing.
Mock token-F1 verdicts have no model reply and write an empty cell. Parsing remains
strict: normalize whitespace/case, accept exactly CORRECT or INCORRECT, reject all
other labels, and serialize the resulting boolean as 1/0. Parser cases for both labels
and surrounding whitespace/case plus verbatim CSV round-trip checks passed; the targeted
evaluation suite passed 22 tests and lint passed.

Reran the configured REAL five-question baseline smoke with answer and judge model
ollama/llama3.2:3b. The first attempt was stopped after sandbox-denied Hugging Face
metadata requests; the network-authorized retry completed. Output:
eval/results/baseline_20261016T110033536916Z.csv. For nw-001 through nw-005, judge_raw
was respectively INCORRECT, CORRECT, INCORRECT, CORRECT, INCORRECT, with correct values
0,1,0,1,0 (2/5). Read the CSV back and verified each serialized label/verdict mapping.
These are actual local-model smoke outputs, not full-benchmark/general quality claims.
Qdrant emitted its existing client 1.19.1/server 1.17.0 compatibility warning; the run
completed successfully. No benchmark report was regenerated from this small smoke run.

Judge robustness follow-up (2026-10-16): Added a case-insensitive verdict-word parser
that searches INCORRECT before CORRECT and records other replies as unparseable, with
an empty correct CSV cell and preserved raw reply. Replaced the strict prompt with
key-fact matching guidance allowing harmless extra words/citations and two short few-shot
examples. Added normalized, nonempty token-boundary reference_in_answer phrase matching
as an independent CSV metric; documented its negation/paraphrase limitations. No evaluation
questions or reference answers were changed. Summaries now include judge accuracy among
parseable verdicts, deterministic reference accuracy, disagreement count/rate and explicit
parsed/unparseable/comparison counts. All-unparseable rates are null rather than zero.
The legacy correctness field aliases judge accuracy; this is answer quality as rated by
the judge, not independently measured judge accuracy against human labels.

Added untimed baseline answer and judge warm-up calls before measured questions, excluding
their replies/latency/tokens/cost from question rows while reporting warm-up usage/cost
separately. Warm-up reduces first-use loading; server eviction/concurrency can still
reload models. Kept shared cache/router benchmark and report consumers compatible with
unknown verdicts: leave request quality NULL, record raw/status, and omit unknown quality
from averages instead of crashing or treating it as incorrect.

Parser, phrase matching, prompt, CSV unknown/verbatim preservation, summary denominators
and warm-up exclusion tests passed. Targeted evaluation/cache-benchmark/report checks
passed 66 tests; the final offline suite passed 1454 tests with one live integration
test deselected in 102.73s. Lint and whitespace validation passed. The unchanged five
REAL questions were rerun with cached embeddings and the configured local models,
writing eval/results/baseline_warm_smoke_20261016T110757201989Z.csv. All five judge
replies parsed as CORRECT (nw-001 and nw-003 included a `### Verdict:\n` prefix),
reference_in_answer was 1 for each, judge/reference accuracies
were both 1.0, disagreement was 0/5, and no verdict was unparseable. Two warm-up calls
were recorded separately. This is an observed five-question smoke run, not general
quality validation or an estimate of the judge's human-label accuracy. Existing Qdrant
version warning and an optional LiteLLM remote-cost-map fetch denial occurred; LiteLLM
used its bundled backup and the run completed. Project reference costs use local PRICES.

Live-Qdrant leakage follow-up (2026-10-16): Confirmed the original test_leakage.py uses
RecordingClient() -> QdrantClient(":memory:"), independent of shell RAG_MODE, and
conftest sets per-test mode to mock. RecordingClient now accepts an explicit URL while
retaining the in-memory default. Added tests/test_leakage_qdrant_integration.py marked
integration and gated by RUN_QDRANT_INTEGRATION=1. Its fixed URL is localhost:6333;
it reuses the exact original 600 user/query assertion cases and both negative controls,
with mock hash embeddings/completions, actual live Qdrant filtering/payload indexes,
and SQLite audit. Enabled service errors fail rather than silently falling back.

Ran the integration suite against the local server: 602 passed in 15.65s (600 cases and
two controls). The disabled-filter control detected forbidden raw chunks while the
Python post-check protected the answer; disabling both defenses produced detected
response leaks. Server info reported Qdrant 1.17.0 and client metadata 1.19.1. The existing
minor-version warning was retained (one warning). Verified no leakage_integration_*
collections remained after fixture cleanup; only its UUID-owned collection was deleted.
Also verified opt-in gating: with flag=0 the two selected controls skipped, 600 cases
deselected. No live-cache, real-model or PostgreSQL claim was made from these checks.

Both original module-scoped harnesses now force mock model mode before ingestion,
because module setup can precede function-scoped conftest fixtures, and close resources
using context managers. Original retrieval/cache suites passed 1205 tests in a targeted
run. After both fixture updates, the full offline suite, launched with RAG_MODE=real,
passed 1454 tests with 603 integration cases deselected in 51.96s. Lint passed. README
and AGENTS now state the precise backend/adapter scope, versions, reproduction command,
opt-in behavior and warning, replacing outdated claims that live Qdrant filtering was
untested. Generated benchmark tables still describe benchmark artifacts; this fixture
run is security integration evidence, not a production leakage-rate/performance result.

## Project 1 sweep, escalation and quality follow-up (2026-10-16)

Extended both guarded/unguarded sweeps through 0.99 with per-threshold
true_paraphrase_hit_rate and false_hits. Full REAL pretrained-embedding sweep:
`eval/results/cache_sweep_20261016T133308209063Z.csv`, 50 pairs per class.
Lowest guarded zero-false-hit threshold is 0.96: 3/50 (6%) paraphrase hits,
0/50 false hits; 0.95 has one false hit. Set CACHE_THRESHOLD default and
.env.example to 0.96; documented tuning limitations and existing-env overrides.

Added ESCALATE_NO_CITATION (default false), first-answer reason capture,
conditional simple-route escalation rates, reason counts/rates and all-request
route shares. Compare now independently clears caches and replays identical
workloads for citation OFF and ON. Primary quality/request-log score is
reference_in_answer; judge_correct/raw/label and judge_accuracy remain secondary.
Report generation uses the recorded quality basis and conditional escalation rate;
legacy CSVs without routes have unknown conditional escalation rate.

Full 75-request/system MOCK (not a result) compare, explicit CACHE_THRESHOLD=0.96:
`eval/results/project1_optimized_20261016T133403252156Z.csv` (OFF) and
`eval/results/citation_policy_on_20261016T133403260168Z.csv` (ON).
Both: quality 47/75, cache hits 24/75; simple 50/75, complex 1/75, cache 24/75;
6/50 simple requests escalated (12%), all weak retrieval; missing citation and
abstention each zero. Mock completion supplies citations; targeted service tests
verify policy ON adds a large-model call for uncited answers while OFF does not.
Full REAL end-to-end compare for these two policies: NOT YET RUN.

Validation: lint passed; full offline suite passed 1460 tests, with 603 integration
cases deselected, in 51.34s. Added tests cover optional citation policy, overlapping
reasons, denominator arithmetic, primary/secondary quality, both policy outputs,
and sweep bounds. An initial report regression on legacy CSVs missing route was
fixed before the passing full rerun. No evaluation questions were changed.

## Graph extraction timeout and salvage follow-up (2026-10-17)

Implemented EXTRACT_TIMEOUT_SECONDS (default 90), at most two extraction retries,
and disabled nested provider retries for extraction only. Three consecutive timeout
or connection failures abort the run with an Ollama/config diagnostic; returned
completions reset the outage streak. Failed chunks are not cached and retry on rerun.
Endpoint-only validation failures now retain declared entities and valid relations,
dropping only relations with undeclared typed endpoints. Other strict schema errors
still fail. Existing valid caches and allowed schema types remain unchanged.

Indexing summaries now record kept_relations, dropped_relations and failed_chunks;
README and generated indexing reports describe these counts and unknown legacy fields.
Session fixture benchmark: MOCK (not a result), 39 paragraphs, 39 kept relations,
0 dropped, 0 failed, no extraction cache hits. Source:
`eval/results/project3_20261017T121344674043Z.json`.
Real extraction/outage behavior for this change: NOT YET RUN.

Validation: lint passed. Full offline suite: 1465 passed, 603 integration cases
deselected in 90.13s. Focused extraction/retrieval/report suite: 41 passed, including
an additional provider-option forwarding regression added after full-suite collection.
Tests cover bounded retries, timeout forwarding, outage abort, reset after completed
invalid JSON, failure retry on a fresh extractor, relation salvage, unknown-type
rejection, cache accounting, summary propagation and README report rendering.

## Extraction token cap and skipped-chunk diagnostics (2026-10-17)

Added EXTRACT_MAX_TOKENS (positive integer, default 700) and forwarded max_tokens
only on graph extraction requests. Completion results preserve finish_reason;
token-limit completions and unexpected JSON EOF skip just that paragraph's graph
extraction immediately. Partial results are not cached, original vector evidence
remains available, and future runs can retry the paragraph. Other validation failures
and the three-consecutive-timeout abort retain their existing behavior.

Summaries now include indexing.skipped_chunk_details (chunk ID, reason, attempts)
and skipped_reasons counts. Indexing writes mode-labeled skipped_chunks.txt even
when no chunks are skipped or an outage aborts. Aborted benchmarks preserve an
incomplete summary and separate archive, without a completed CSV reference.
README, AGENTS and .env.example document configuration and diagnostics; generated
skipped_chunks.txt is ignored by Git.

Session verification: MOCK (not a result) fixture benchmark completed 15 questions
with 39 kept relations and zero skipped chunks; empty details/counts and a mode-only
skipped_chunks.txt were produced. Artifact: project3_20261017T124446863284Z.json.
Five new regression tests passed, covering configurable cap forwarding, provider
finish metadata and JSON EOF truncation, continuation to the next chunk, no failure
caching, and validation/timeout summary and file persistence. Full offline suite:
1471 passed, 603 integration cases deselected in 111.68s. Lint passed.
Live-provider token-limit behavior for this change: NOT YET RUN.

## Constrained schema, repair and live verification (2026-10-18)

Extraction now forwards the fixed Extraction JSON schema via LiteLLM json_schema
response_format, adding maxItems=8 for entities and relations. Prompt requests only
important explicit facts; EXTRACT_MAX_TOKENS defaults to 1000. Entity/relation type
lists remain unchanged. Lenient repair handles string entities, blank names, requested
entity aliases and OTHER fallback, unknown predicates as RELATED_TO, and dangling
relations after typed-endpoint repair. Other malformed structures still fail strictly.

Indexing summaries and README reporting count fresh attempted/clean/repaired/failed
chunks, entity/relation type repair occurrences, dropped relations, string coercions
and dropped entities. Cache hits retain zero new calls and are excluded from fresh
classification because historical repair provenance is unknown. Failures remain uncached.
Console diagnostics are one short skipped-chunk ID/reason; full per-attempt errors and
raw replies append to extraction_failures.log. Test logs use temporary directories.

Inspected installed LiteLLM 1.105.1 Ollama completion/chat adapters: json_schema maps
to Ollama's schema-valued format. CLI and server API both report Ollama 0.40.5.
Ran three fresh real ollama/llama3.2:3b calls on authored film, band and oil-field
paragraphs; raw entity and relation objects were validated BEFORE repair. All three
used only fixed allowed types and ended with finish_reason=stop (259/187/146 output
tokens), without truncation. Attempted 3, clean 2, repaired 1, failed 0; entity-type
repairs 0, relation-type repairs 0, dangling relations dropped 2, kept relations 6.
Artifact: eval/results/extraction_schema_smoke_20261018T073650034507Z.json.
This verifies the live schema path on three cases, not full-corpus semantic quality.
Reproduce with python -m scripts.verify_graph_extraction in real mode at cap 1000.

Fresh MOCK (not a result) fixture benchmark: 39 attempted/clean, 0 repaired/failed,
0 type repairs or dropped relations; project3_20261018T073843118105Z.json.
Full real benchmark for this change: NOT YET RUN.

Validation: lint passed; full offline suite passed 1492 tests, with 603 integration
cases deselected in 158.63s. Focused repair/report tests: 36 passed. Tests cover all
requested aliases, fixed type lists, OTHER/RELATED_TO fallback, endpoint repairs,
dropped blanks/dangling relations, schema forwarding and limits, summary/report
accounting, one-line console failures and full temporary-file diagnostics.

## Completion defaults and resilient graph benchmark (2026-10-18)

Shared complete() now always forwards finite timeout/max_tokens and disables provider
retries. Defaults: LLM_TIMEOUT_SECONDS=120, LLM_MAX_TOKENS=400; extraction retains
explicit 90-second/1000-token bounds. rg over app/graphrag/eval/scripts confirmed the
only direct LiteLLM completion call is this centrally bounded adapter; decomposition
and all other complete() callers cannot inherit the provider's 600-second default.

Graph benchmark now defaults to vector,graph_hybrid and supports comma-separated
--systems with explicit decomposition opt-in. Each question/system generation exception
becomes a failed result with reason/timeout status; remaining work continues. Summaries
report completed/failed/timed_out/invalid_decomposition by system. Invalid planner JSON
still falls back and its count survives fallback failure. Failed rows score zero quality
and retain unknown partial usage as null; completed subset statistics remain available.

Terminal question results are immediately checkpointed with flush/fsync to JSONL and
reused on matching reruns, including recorded failures. Checkpoints isolate workload,
mode/models/endpoint/limits/resolution, recover an interrupted trailing write, and reject
earlier corruption. Model/corpus/config changes select a new checkpoint. New systems
can reuse existing system results. Summary records resumed_results/new_results; reports
support selected subsets and explicitly unknown failed-row usage. README/AGENTS and
.env.example document controls, restart behavior and per-call timeout scope.

Validation: lint passed; focused tests 46 passed. Full pytest collection in mock mode
with live-service opt-ins cleared only in the child process:
`1502 passed, 603 skipped in 66.54s (0:01:06)`.
Skipped cases are live Neo4j/Qdrant integration tests. Added regression tests cover one
timeout followed by successful questions, generation failures, checkpoint reuse after
failure/interruption, invalid plans with failed fallbacks, limit forwarding/overrides,
partial writes, configuration isolation and invalid system selections.
Mock CLI verification (MOCK, not a result): two questions across two default systems;
second run reused 4 terminal rows, new_results=0. Live provider timeout/recovery for this
change: NOT YET RUN. No real performance or quality result is claimed.

## Subset-safe entity resolution and extraction-cost provenance (2026-10-18)

Replaced token_set_ratio with normalized plain RapidFuzz ratio >=92. Non-person token
subsets stay separate even with optional embeddings; only PERSON two-token first/last
names may match longer names with inserted middle tokens. Type separation, normalization,
longest canonical names and complete-link checks remain. Merge reports and indexing
summaries now contain merge_counts by normalized_equal/person_first_last/ratio/embedding;
these count eliminated unique typed entities and sum to raw minus canonical count.

Regenerated REAL merge_groups.txt from the exact same 20-question/200-paragraph HotpotQA
sample, using 200 successful cache reads and forbidding new provider calls. Raw unique
typed entities: 966; canonical: 956. Merges: 3 normalized-equal, 3 person first/last,
4 plain-ratio, 0 embedding. All five user examples remain separate. This is resolver-only
verification, not a fresh QA quality/performance result. Evidence:
eval/results/resolution_rebuild_20261018T173547647813Z.json. The dataset was read from its
cached Arrow file with in-memory sampling after the normal loader attempted a sandbox-
blocked external cache lock; no dataset content was changed or downloaded.

Added --fresh-extraction and first_fill_extraction summary fields. New successful cache
fills persist original time/tokens/completed-call/reference-cost measurements in per-key
provenance records; cache hits and forced regeneration preserve original measurements.
Current-run counters remain separate. Failed extractions are not written as cache entries;
first-fill totals deduplicate cache keys. All 200 legacy real entries lack provenance, so
their historical totals are unknown/null, never zero. Later fresh measurement cannot
reconstruct the past. Real fresh extraction/QA benchmarking for this change: NOT YET RUN.
Resolved graph fingerprints invalidate stale QA checkpoints after evidence/merge changes.

Validation: lint passed. Full offline test collection: 1513 passed, 603 live integration
cases skipped in 152.50s (0:02:32). New cases cover all five subset examples, spelling
similarity, PERSON-only exceptions, type separation, embedding-guard behavior, original
fill persistence across cached/fresh runs, legacy unknowns and benchmark summary counts.
Mock CLI (MOCK, not a result) fresh/cached verification: 0 then 39 cache hits, identical
original-fill metrics across runs; artifacts under data/runtime/first fill verification.
README/AGENTS/DECISIONS explain measurement scope and remaining fuzzy-match risks.

## Graph benchmark progress lines (2026-10-19)

Extraction prints flushed progress every ten paragraphs and at the final remainder:
done/total, failed chunks so far and elapsed seconds, with explicit runtime-mode labels.
Extraction diagnostics go to stderr to preserve the standalone graph CLI's JSON stdout.
Evaluation prints one done/total line per question/system, including completed/failed
statuses and checkpoint-resumed results. New-result progress follows durable checkpoint
writes; checkpoint data and resume behavior are unchanged.

Extended existing regressions to verify extraction cadence/totals and evaluation progress
for all systems, failures and checkpoint reuse. An initial full-suite run exposed stdout
pollution of the public JSON CLI; moved extraction progress to stderr and reran all tests.
Final validation: lint passed; 1513 tests passed, 603 live integration cases skipped in
61.24s (0:01:01), with mock mode and live-service opt-ins disabled in the test child process.

## Archived-evidence README refresh (2026-10-20)

Rebuilt README as a compact pitch, architecture diagram, baseline/project tables,
verification scope, limitations and Details link. Moved operational detail/design
history into docs/IMPLEMENTATION_NOTES.md and removed obsolete run-status claims.
Only decomposition retains NOT YET RUN. Numeric README results are computed from
explicitly named results_archive files, with adjacent filename links; archives were
not modified. The README is below the requested top-level length budget.

Verified the provided evidence by script: hand_labels.csv contains 41/45 human-correct
answers, reference/human agreement 39/45 (rounded 87%) and judge/human agreement 33/45
(rounded 73%). The selected comparison CSV has 10 cache hits with matching references;
the guarded sweep at 0.90 has 2 false hits among 50 near misses. Archived comparison
latency deltas round to +4.2s/+22.5s, with 43% simple-route escalation. The comparison
summary filename identifies threshold context but lacks explicit threshold/guard fields;
README states the user's supplied settings and discloses this metadata gap.

Graph tables use the final archived CSV/summary, disclose absent single-hop/decomposition
results, partial first-fill measurements (400/600), mixed code versions and historical
stalls/timeouts. Live Qdrant fixture evidence is separated from deterministic mock
embeddings/SQLite audit and unverified PostgreSQL triggers/Docker API deployment.
Observed archived timeouts and completed evaluation do not become a controlled recovery
test claim. Local-model costs remain estimates at reference prices.

Added an explicit archived-results report mode that regenerates the compact cited tables
without replacing editorial limitations or reverting to newer mock runs. Generic latest
real/mock reporting remains available for other documents. Tests cover calculations,
citations, idempotence and summary/CSV mismatch rejection before rewriting.
Ran the report generator and lint successfully. Focused report tests: 18 passed.
Full offline collection: 1516 passed, 603 live integration cases skipped in 163.27s
(0:02:43), with live opt-ins disabled only in the test child process.

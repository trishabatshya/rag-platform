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

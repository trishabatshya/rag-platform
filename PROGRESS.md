# Progress

- [x] M0: Scaffold (mock acceptance passed; real-provider validation pending)
- [x] M1: Baseline RAG and evaluation (mock acceptance passed)
- [x] M2: Permission-aware multi-tenant RAG (mock acceptance passed)
- [x] M3: Semantic cache and routing (mock acceptance passed)
- [ ] M4: GraphRAG
- [ ] M5: Integration and polish

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

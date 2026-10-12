# Northwind RAG Platform

```mermaid
flowchart LR
    Client --> API[FastAPI]
    API --> Identity[Verified JWT]
    Identity --> Cache[Tenant and permission scoped cache]
    Cache --> Retrieval[ACL filtered vector retrieval]
    Retrieval --> Router[Small or large local model]
    Router --> Answer[Answer with citations]
    API --> Audit[Append only audit log]
    Graph[Graph expansion and reranking] --> Retrieval
```

A RAG platform for studying permission enforcement, semantic caching and multi-hop
retrieval with reproducible evaluations. Development follows M0–M5 in TASK.md.
**Current status: M3 semantic caching and cost-aware routing**. The API verifies JWTs,
isolates cached answers by permission scope, filters/rechecks retrieval, selects a model
and escalates weak answers. Retrieval and cache hits are audited and requests measured.
The public Northwind baseline remains available through the offline evaluation harness.
Graph retrieval and final reporting remain planned for M4-M5.
The mock installation and checks pass on Windows with Python 3.11.9. Docker Compose
configuration validates; container startup and the real model adapters are unverified.
Ollama was unavailable in the development environment.

## Windows 11 quickstart (PowerShell)

```powershell
py -3.11 -m venv .venv311
.\.venv311\Scripts\Activate.ps1
$env:RAG_MODE="mock"
python tasks.py install
python tasks.py lint
python tasks.py test
python tasks.py eval
python tasks.py run
```

If PowerShell blocks activation, use `.\.venv311\Scripts\python.exe` instead of
`python`. The `/health` endpoint is available at http://localhost:8000/health.
Use `Copy-Item .env.example .env` for configuration. Do not commit .env.
Mock mode runs without Docker, a model download, an API key or network access
after dependencies have been installed. Dependency installation needs package access.

On POSIX: `python3.11 -m venv .venv`, activate `.venv/bin/activate`, then run
`RAG_MODE=mock python tasks.py test`. A Makefile is available when make is installed.

All targets work through `python tasks.py TARGET` or `make TARGET`:
`install`, `test`, `lint`, `up`, `down`, `ingest`, `run`, `eval`, `bench-cache`,
`bench-acl`, `bench-graph`, `dashboard`, `report`. Later feature targets are wired
now; their modules will be implemented in the milestones listed in PROGRESS.md.
Extra arguments are forwarded, for example `python tasks.py test -q`.

## Baseline RAG and evaluation

The committed Northwind Cloud corpus contains 20 fictional Markdown documents,
including similar EU/US refund policies and Pro/Team plan descriptions. The reviewed
starter evaluation has 45 hand-written questions: 40 answerable and 5 not in the corpus.
These fixtures are fictional product facts, not measurements of a real service.

```powershell
$env:RAG_MODE="mock"
python tasks.py ingest
python tasks.py eval --tag baseline --limit 45
python tasks.py run
```

The baseline evaluator uses the isolated `baseline_chunks` collection. The authenticated
HTTP API uses the ACL-protected `chunks` collection and the fictional tenant corpus.
In a second PowerShell window, log in and send a tenant question:

```powershell
$credentials = @{username="acme.engineer"; password="demo-password"} | ConvertTo-Json
$login = Invoke-RestMethod -Uri http://localhost:8000/auth/login -Method Post -ContentType "application/json" -Body $credentials
$headers = @{Authorization="Bearer $($login.access_token)"}
$body = @{question="What deployment cluster does Acme engineering use?"} | ConvertTo-Json
Invoke-RestMethod -Uri http://localhost:8000/ask -Method Post -Headers $headers -ContentType "application/json" -Body $body
```

`POST /ask` accepts only a question and returns answer, cited sources, up to five
retrieved chunks with provenance and scores, model, token counts and measured latency.
With valid authentication, blank questions receive HTTP 422. Missing, expired or tampered
tokens receive HTTP 401. Numbered citations determine `sources`; the complete retrieved
source list is available in `chunks`. Identity comes exclusively from signed JWT claims;
body fields such as `tenant_id`, `roles` or `user_id` are ignored.

Chunking targets 400 words with 60 words of overlap, preferring paragraph boundaries.
Re-ingestion replaces a folder's documents, removes stale chunks and bumps a SQLite
corpus version. Sources are paths relative to the document folder, with forward slashes
on every OS. Document IDs incorporate the resolved folder path and chunk IDs are stable
for unchanged chunk positions. Moving the folder changes document IDs.

**Mock indexes are process-local.** A separate `ingest` command demonstrates ingestion
but cannot populate a future process's in-memory Qdrant. Mock service/evaluation processes
reload their configured corpus on first use: `RAG_DOCS_DIR` for baseline evaluation,
`RAG_SEED_DIR/documents.json` for the authenticated API. Real ingestion writes to Qdrant.
Use the same `RAG_STATE_DB` for ingestion and serving so they share corpus version metadata.
That metadata is currently local SQLite even when the vector server is remote.

For a custom corpus:

```powershell
$env:RAG_DOCS_DIR="C:\My documents\Northwind"
$env:RAG_STATE_DB="C:\My documents\Northwind state.db"
python tasks.py ingest --corpus baseline
```

Use a matching evaluation dataset when evaluating a custom corpus:
`python tasks.py eval --dataset "C:\My documents\reviewed eval.jsonl" --tag custom`.

The evaluation writes `eval/results/{tag}_{UTC timestamp}.csv`, with per-question
answers, retrieved/cited sources, expected-source hit, correctness, latency, tokens,
reference-price cost, corpus version and runtime mode. Correctness includes unanswerable
questions; hit rate includes only questions with an expected source. p50/p95 and mean
cost describe the actual run. Judge overhead is recorded separately from answer cost.
Every mock CSV row is labeled `MOCK`, and console output says `MOCK (not a result)`.

Mock judging uses case/punctuation-normalized multiset token F1, excluding citations,
and labels F1 >= 0.5 correct. It can incorrectly accept answers with a wrong number or
entity. The mock LLM quotes context rather than providing a realistic concise answer,
so its correctness scores do not measure answer quality. Real judging requests
`CORRECT` or `INCORRECT` from the configured judge model at temperature zero.

Costs are **estimated at reference prices** from `app/config.py:PRICES`, in USD per
million input/output tokens. M3 verified the reference tiers against the published
[GPT-4o Mini](https://developers.openai.com/api/docs/models/gpt-4o-mini) and
[GPT-4o](https://developers.openai.com/api/docs/models/gpt-4o) text-token prices on
2026-10-12. Those tiers are comparison proxies for the configured small/large models,
not charges for local Ollama calls. `REFERENCE_SMALL_INPUT`, `REFERENCE_SMALL_OUTPUT`,
`REFERENCE_LARGE_INPUT` and `REFERENCE_LARGE_OUTPUT` can override rates for another
comparison. A small call followed by a large escalation is charged at each call's own
reference tier; optional router-classifier tokens are included too.

## Permission-aware RAG (Project 2)

`data/seed/` contains three fictional tenants (Acme, Globex, Initech), five users per
tenant and six documents per tenant. The documents cover public FAQs, employee
onboarding, engineering wikis, confidential HR salaries, board notes and user-only
contractor instructions. Distinct marker strings make leaks detectable offline.
All users have the intentionally public **demo-only** password `demo-password`;
committed user records contain salted PBKDF2-SHA256 hashes, not plaintext passwords.

Demo usernames are `acme.employee`, `acme.engineer`, `acme.hr`, `acme.admin` and
`acme.contractor`; replace `acme` with `globex` or `initech` for the other tenants.
Contractors have no role grants and exercise explicit-user access. Administrators have
no implicit bypass: an explicit-user-only document is not readable by an admin unless
its metadata also grants that admin access.

Every ACL chunk requires `tenant_id`, `allowed_roles` and `classification`, with optional
`allowed_users`. The vector query requires tenant equality **and** at least one matching
role or user grant, using Qdrant's `min_should` with `min_count=1`. Even a `public` document
requires the same tenant and an explicit grant. Classification is a validated label
(`public`, `internal`, `confidential`), not an additional inferred clearance system.
The post-check drops malformed or forbidden evidence, emits a critical log entry, and
increments the tenant's counter before any context is sent to the LLM.

Run the security checks and benchmark from PowerShell:

```powershell
$env:RAG_MODE="mock"
python tasks.py test tests/test_leakage.py
python tasks.py bench-acl --queries 200
python tasks.py ingest --corpus seed
```

The leakage suite parametrizes every seeded user over 40 adversarial questions
(600 combinations). Its oracle derives forbidden documents and markers from the seed
data, independently of the production filter. It checks raw vector results, returned
chunk IDs/text and generated answers, and requires accessible documents to be returned.
Negative controls disable the filter and then both defenses, proving the oracle detects
leaks. HTTP tests use genuinely signed local JWTs and cover body spoofing, missing,
expired, tampered and unsupported-algorithm tokens. These are mock security regression
tests, not real-model quality or production-scale performance measurements.

The ACL benchmark creates a disposable collection, alternates filtered/unfiltered query
order over at least 200 pairs, writes per-pair timings and prints median paired overhead.
It tests that a previously accessible document is absent from the very next query after
revocation. Filtering timings measure raw vector operations only; they exclude embedding,
model generation and production audit overhead. Revoke-to-effect timing includes epoch
increment, payload update and one verification query. All mock rows are labeled `MOCK`.
The unfiltered path exists only inside this isolated benchmark, never as an API option.

### Administrator endpoints and audit

The verified `admin` role is required for:

- `GET /admin/metrics`: process-local post-check drops for the caller's tenant.
- `GET /admin/doc-access/{doc_id}?days=30`: exact document access records, tenant-scoped;
  `days` must be between 1 and 365.
- `PATCH /admin/docs/{doc_id}/acl`: replace all role/user grants and classification
  on every chunk of a document in the caller's tenant. Cross-tenant IDs return 404.

For example, after logging in as `acme.admin`, revoke engineering access:

```powershell
$credentials = @{username="acme.admin"; password="demo-password"} | ConvertTo-Json
$login = Invoke-RestMethod -Uri http://localhost:8000/auth/login -Method Post -ContentType "application/json" -Body $credentials
$headers = @{Authorization="Bearer $($login.access_token)"}
$acl = @{allowed_roles=@("admin"); allowed_users=@(); classification="confidential"} | ConvertTo-Json
Invoke-RestMethod -Uri http://localhost:8000/admin/docs/acme:engineering-wiki/acl -Method Patch -Headers $headers -ContentType "application/json" -Body $acl
Invoke-RestMethod -Uri "http://localhost:8000/admin/doc-access/acme:engineering-wiki?days=30" -Headers $headers
```

Updates wait for Qdrant completion and advance the persisted `cache_epoch` before
mutation, invalidating cached answers. A process-local lock serializes retrieval
snapshots and admin updates in the single-worker API. Already-running generation can
finish using its earlier snapshot. Mock ACL edits reset to committed fixtures on process
restart; SQLite audit history and the epoch persist.

Every authenticated retrieval is committed to `audit_log` before generation, including
empty results and failed vector queries. Audit failure blocks generation. Records contain
request ID, UTC time, verified user/tenant, query, delivered chunk/document IDs and model.
An exact-match evidence index avoids substring matches in document access queries.
The offline public baseline evaluator and raw isolated benchmark are separate from this
authenticated request path.

Mock audit uses SQLite at `RAG_AUDIT_DB` even when DATABASE_URL names Postgres. SQLite
triggers reject UPDATE/DELETE and replacement of existing identities on both audit tables;
the store exposes append/read only.
Real mode uses SQLAlchemy/psycopg with PostgreSQL. After table creation, startup applies
`migrations/001_append_only_audit.sql`, whose statement triggers reject UPDATE, DELETE
and TRUNCATE. The migration syntax was checked against
[PostgreSQL 16's trigger documentation](https://www.postgresql.org/docs/16/sql-createtrigger.html),
but has not been executed against a live server here. A database owner can disable or
drop triggers; production needs a separate migration owner and restricted application
role. SQLite file owners can also alter the database outside the application.

Mock JWT signing uses a randomly generated process-local key when `JWT_SECRET` is empty.
Real mode requires an explicitly configured key of at least 32 bytes. Generate one for
a local real-mode process without committing it:

```powershell
$env:JWT_SECRET = python -c "import secrets; print(secrets.token_urlsafe(48))"
```

For Docker or multiple workers, put the same random key in the ignored `.env`. Default
token lifetime is one hour (`JWT_TTL_SECONDS`). Demo authentication has no account
provisioning, refresh/revocation service or login rate limiting; role changes require
a new token, while document ACL revocation affects the next query immediately.

## Semantic cache and model routing (Project 1)

The `/ask` service embeds a normalized question, checks a separate vector cache, then
on a miss retrieves permitted evidence, routes to the small or large model, and escalates
a small-model answer when evidence is weak, no valid citation exists, or it says
`I don't know`. Each returned response retains the original RAG interface. Detailed
route, cache, escalation, usage and reference-cost measurements go into `requests`.

A cache hit requires all of the following:

- Similarity at least `CACHE_THRESHOLD` (initially 0.90).
- Matching corpus version and current ACL epoch.
- Nonnegative age below `CACHE_TTL_SECONDS` (initially 600 seconds).
- Same verified tenant, sorted-role fingerprint **and user ID**.
- Matching number/entity sets when `CACHE_GUARD=true`.

The user-ID key is necessary because two users with the same roles can have different
explicit-user grants. Cache queries apply scope/version/epoch/age predicates inside
Qdrant, followed by application checks. Up to ten matching neighbors are considered
so a guard rejection does not force a miss when another eligible entry exists.
Before serving a hit, the service queries the stored evidence IDs with the current ACL
pre-filter, rechecks metadata and verifies unchanged text/provenance. It then writes an
audit entry with `cache_hit=true` and the evidence document IDs. Cache hits incur zero
new LLM tokens; lookup, evidence checking and audit work still take time.

Empty, uncited, abstaining or failed responses are not cached. A corpus/ACL change during
generation prevents storing that older snapshot. `SemanticCache.clear()` clears its own
collection. The number/entity guard is conservative: it can reject valid aliases or
capitalization variants and does not identify all operation-direction or negation flips.
Semantic similarity is not proof of equivalent questions.

The rule router uses question length, complexity words, rough entity count, retrieval
top score and score spread. `ROUTER_MODE=llm` enables a small-model one-word classifier;
invalid labels fall back to the large-model route. That classifier sees only the verified
caller's question and runs before retrieval. For rule routing, a pure callback selects
the model after the ACL post-check and before the retrieval audit commits, so the audit
records the actual model choice. Both paths audit evidence before answer generation.

Run the complete Project 1 experiments:

```powershell
$env:RAG_MODE="mock"
python tasks.py bench-cache
python tasks.py dashboard
```

Or run an individual experiment:

```powershell
python -m eval.bench_cache_router --sweep
python -m eval.bench_cache_router --router
python -m eval.bench_cache_router --compare --repeat-ratio 0.40
```

The sweep evaluates thresholds 0.85 through 0.97 against 50 curated paraphrase pairs
and 50 near-miss pairs, with and without the guard. It reports the lowest threshold with
zero false hits on this tuning set, or reports none. These are pairwise comparisons,
not a held-out evaluation of every competing cache entry. Do not select a real deployment
threshold from mock embedding scores. Regenerate the fixtures with
`python -m scripts.make_paraphrases`.

The router experiment evaluates both classifiers on 100 hand-labeled intent questions,
including simple questions containing complexity words and multi-step questions without
them. It separately measures answer quality/reference cost for always-large, rule and
LLM routing on the reviewed baseline evaluation. Classifier accuracy and answer quality
are separate measurements; labeling a question correctly does not guarantee a correct
answer.

The comparison copies the public sample corpus into a disposable ACL-protected benchmark
collection. It replays the same seeded mixed workload through always-large/no-cache and
the new service after clearing its cache. The default workload is 40% repeats; half of
repeat events use a template paraphrase. Repeats follow an earlier occurrence of their
source question. Both requested and actual repeat ratios are written to outputs because
small `--limit` runs require rounding. Indexing happens before the measured replay.
The benchmark writes baseline/optimized request CSVs and `summary_project1.json` with
cost reduction, p50/p95 changes, judged quality delta, cache hit and escalation rates.
Rows account for both escalation calls and optional classifier usage; judge cost is
separate. Benchmark latency wraps the whole service, including request logging, and
excludes the subsequent reference judge.

The dashboard at http://localhost:8501 shows reference cost/request, cache hit rate,
route split, escalation rate, latency percentiles and judged quality by route over time.
Filter by runtime mode and `run_tag`; API calls use `RUN_TAG` and benchmarks create
distinct tags. `RAG_REQUESTS_DB` selects the SQLite log in mock mode; real mode uses
PostgreSQL. Ordinary API quality is unknown (`NULL`) until a reference judge runs;
the dashboard displays that absence rather than assigning a quality score. Its logged
latency ends just before the final request-log commit; benchmark CSVs also capture that
commit's wall time. The dashboard is a local operator tool without tenant login.

All mock CSV/JSON outputs and the dashboard prominently say `MOCK (not a result)`.
Mock answers still quote context, so their F1 correctness is not model quality. No mock
savings, latency or accuracy measurements populate the real-results table below.

## Corpus helpers and human review

Download user-specified public **plain-text or Markdown** URLs listed one per line:

```powershell
python -m scripts.fetch_corpus urls.txt --output-dir data/docs
```

The helper reports each failure and keeps successful downloads when network access
is unavailable. It saves response text as UTF-8 `.txt`; it does not extract main content
from HTML pages. Downloaded data is ignored by Git.

Generate candidate evaluation items without overwriting the reviewed dataset:

```powershell
python -m scripts.gen_eval --docs data/docs_sample --output data/eval_candidates.jsonl
```

Every generated item has `needs_review: true`. Review the question, reference and
source against the actual document, then set `needs_review: false` and promote selected
items into the reviewed dataset. The evaluator rejects items still marked for review.
Mock generation produces deterministic draft templates for software checks only.
The generator refuses to overwrite `data/eval.jsonl` or an existing candidate file.

Sample up to 30 judged rows, fill `human_verdict` with `CORRECT` or `INCORRECT`, then
calculate agreement over completed rows:

```powershell
python -m eval.judge_check "eval/results/baseline_TIMESTAMP.csv" --output eval/results/judge_review.csv
python -m eval.judge_check eval/results/judge_review.csv --agreement
```

Replace `baseline_TIMESTAMP.csv` with a CSV produced by your evaluation. Sampling is
seeded and does not overwrite existing human work. An untouched sample has no agreement
score, rather than claiming that human validation occurred.

## Containers

`docker compose up --build` starts Qdrant, Postgres 16, Neo4j 5 and the API.
The API defaults to mock mode. Set `RAG_MODE=real` in .env to opt into real adapters.
Database credentials in compose are public development defaults; replace them
before deploying. Container Ollama calls use `host.docker.internal:11434`.

## Producing real results

No real benchmark has run yet. Baseline, ACL and cache/router experiments and the
dashboard are implemented; graph and final report commands require later milestones.
Real model adapters require sentence-transformers and LiteLLM (optional dependency
setup and installed-API verification remain pending, as recorded in PROGRESS.md).

```powershell
ollama pull llama3.2:3b
ollama pull qwen2.5:7b
Copy-Item .env.example .env
$env:RAG_MODE="real"
$env:SMALL_MODEL="ollama/llama3.2:3b"
$env:LARGE_MODEL="ollama/qwen2.5:7b"
$env:JWT_SECRET = python -c "import secrets; print(secrets.token_urlsafe(48))"
docker compose up -d qdrant postgres neo4j
python tasks.py ingest
python tasks.py eval
python tasks.py bench-acl
python tasks.py test tests/test_leakage.py
python tasks.py bench-cache
python tasks.py bench-graph
python tasks.py report
```

Review the evaluation dataset, human judge verdicts, merge groups and failure
analysis before publishing results. Cost estimates will use explicitly labeled
reference prices, since local models do not incur paid API charges.

<!-- RESULTS:START -->
| Project | Real measurements |
| --- | --- |
| Baseline RAG | NOT YET RUN |
| Permission-aware retrieval | NOT YET RUN |
| Semantic caching and routing | NOT YET RUN |
| GraphRAG | NOT YET RUN |
<!-- RESULTS:END -->

Dashboard screenshot: pending a real run; the dashboard is implemented and headless-tested.

## Limitations

Mock embeddings and answers test software contracts, not retrieval quality.
Ingestion prepares documents before writing, but SQLite and Qdrant are not a single
transaction: a Qdrant write failure can leave a partially replaced corpus. Re-ingest
after a failure, and avoid querying while ingestion runs. The baseline evaluator remains
public-only; authenticated tenant data must use ACL ingestion and the separate collection.
The current epoch store and security counters are local, and the demo service is intended
for one worker. Production horizontal scaling requires shared invalidation state and
centralized metrics. Real Qdrant filtering/indexes and PostgreSQL triggers remain untested
with live services; the implemented security regression checks ran in mock mode.
Cache hits deliberately revalidate evidence, which costs extra vector/audit work. Small
hand-curated tuning and router sets do not establish production hit rates or quality;
capitalized-token guards miss some action/negation differences. Generation that started
before an ACL update can finish its earlier snapshot, but that snapshot is not inserted
into the new epoch. Request errors record usage from completed calls; unreturned provider
usage is unknown. Dashboard browser interaction, live model routing and live database/
vector behavior have not been exercised here; Streamlit was tested headlessly.
The finished evaluation must account for a small corpus, LLM judge bias, estimated
reference costs, semantic cache false hits, extraction and resolution errors,
GraphRAG indexing cost, and demo-grade authentication. See DECISIONS.md for trade-offs.

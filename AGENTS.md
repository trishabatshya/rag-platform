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

## Layout

- app/: config, embeddings, completions, vector store, baseline RAG, auth, ACL,
  secure_rag, append-only audit; cache/service arrive in later milestones.
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
before mutation. Cache-hit audit/invalidation integration will be implemented in M3/M5.

The leakage oracle must read seed grants directly rather than production ACL functions.
Test raw query results, response chunks and answer markers, plus positive access and
negative controls. Benchmark unfiltered calls belong only in a disposable collection
and measure raw operations, not authenticated end-to-end latency. Mock metrics must never
be promoted into README real-result tables.

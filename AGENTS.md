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

- app/: configuration, embeddings, completions, vector store, then RAG/auth/ACL/cache/service.
- graphrag/: dataset, schema, extraction, resolution, storage and retrieval.
- data/: docs_sample, seed, eval.jsonl, cache_pairs, router_labels.jsonl, graph_fixture.
- scripts/: corpus/data helpers and report generator.
- eval/: evaluation and benchmark runners; results/ holds generated outputs.
- tests/: offline contracts and regression suites.
- docs/: interview study notes.
- tasks.py / Makefile: portable tasks; Dockerfile / docker-compose.yml: deployment.

Shared contracts: `embed(list[str]) -> np.ndarray` (float32, normalized, n x 384),
`complete(prompt, model, system=None, json_mode=False) -> LLMResult`.
The baseline `rag_pipeline(question, model, user=None) -> dict` returns
answer, sources, chunks (id, score, text, source, doc_id), model, in_tokens,
out_tokens and latency_ms. Keep these interfaces stable as later milestones land.

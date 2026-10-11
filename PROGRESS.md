# Progress

- [x] M0: Scaffold (mock acceptance passed; real-provider validation pending)
- [ ] M1: Baseline RAG and evaluation
- [ ] M2: Permission-aware multi-tenant RAG
- [ ] M3: Semantic cache and routing
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
M1 is the first unfinished feature milestone. Before any real-mode evaluation,
install and inspect provider dependencies, pin them, and validate both adapters.

# Decisions

## M0

- **Portable commands:** tasks.py uses sys.executable, pathlib and subprocess argument
  lists with shell=False. Alternatives were shell scripts and duplicated Makefile
  recipes. One runner keeps Windows and POSIX behavior consistent.
- **Python version:** use the installed Python 3.11 interpreter in .venv311; the
  machine defaults to 3.14. Python 3.11 matches the task and container runtime.
- **Mock embedding:** SHA-256 token feature hashing with signed buckets, normalized
  to 384 dimensions. A fixed fallback vector handles empty/cancelled text. This
  enables deterministic lexical similarity without claiming semantic quality.
- **Dependencies:** keep mock requirements separate from expensive real-model
  packages. Real adapters import providers only when called. Real-mode packages
  must be installed and inspected before their APIs can be declared validated.
- **M0 feature scope:** provide a working health endpoint and adapter contracts;
  later target commands point to their milestone modules. Do not add fake success
  handlers or empty implementations for unfinished features.
- **Compose:** persist all service data in named volumes. Missing .env is allowed
  using Compose's optional env_file support; development defaults are public.
- **Validation boundary:** M0's offline acceptance commands pass. The optional
  real-provider download did not finish and was stopped, so real model APIs have
  not been validated or pinned. Treat real adapters as unverified until the
  installed implementations are inspected. Docker configuration validation passed,
  but the daemon check did not return and Ollama is not on PATH.
- **Installed API detail:** QdrantClient 1.19.1 has query_points and collection_exists,
  but is not a context manager. Tests use contextlib.closing. Starlette 1.7.0 emits
  a deprecation warning for httpx-backed TestClient; tests pass with the installed
  httpx 0.28.1. Revisit the transport dependency before upgrading the HTTP tests.

## M1

- **Process-local mock index:** service and evaluation reload the configured sample
  corpus on first use. A separate mock ingestion process cannot share an in-memory
  Qdrant client. Alternatives were persistent local Qdrant or an HTTP ingestion
  endpoint; reload preserves M0's required in-memory mock adapter and simple CLI.
- **Version and IDs:** a SQLite transaction serializes version increments and tracks
  folder manifests. Every successful ingestion, including identical re-ingestion,
  bumps the version. UUID5 IDs use resolved folder path, relative source and chunk
  position; re-ingestion does not duplicate points. Sources use portable forward
  slashes, but moving the corpus folder changes its IDs. Removed documents and
  shortened documents lose stale chunks.
- **Cross-store failure:** all text decoding and embedding precede mutation; version
  metadata advances only after Qdrant writes complete. Qdrant and SQLite are not
  transactionally coupled. A vector write failure can leave partial replacements;
  rerun ingestion and do not serve during ingestion. Atomic index swaps are deferred.
- **Retrieval provenance:** response sources are parsed citations; evaluation hit
  uses all retrieved chunk sources. Unanswerable items have a null source and a blank
  hit cell, excluded from hit rate but included in correctness. This avoids treating
  an expected absence of a source as a retrieval failure.
- **Judge limitation:** mock correctness uses multiset token F1 >= 0.5, as requested.
  This is a weak lexical metric that can pass wrong-region/wrong-number answers.
  Mock completions quote whole context, so their correctness is not a model-quality
  result. Real binary judging is implemented but unverified with a live provider.
  Human-review samples use a fixed seed, preserve blanks, and refuse overwrite.
- **Reference prices:** initial tier prices are illustrative assumptions in USD per
  million tokens, not asserted provider list prices or actual local-model charges.
  Evaluation separates judge tokens/cost from answer tokens/cost and rejects an
  unknown model price tier. Update assumptions before interpreting real savings.
- **Public-corpus boundary:** M1 has no authentication. It rejects retrieved chunks
  carrying tenant_id rather than silently treating them as public. User identity
  arguments are rejected until M2 implements the authenticated retrieval path.
- **Installed APIs:** inspected QdrantClient 1.19.1 delete/filter/scroll interfaces.
  Pydantic on Python 3.11 requires typing_extensions.TypedDict for response schemas;
  updated the existing contracts import while preserving its fields.
- **Helpers:** fetch accepts only HTTP(S) URLs and stores decoded response text;
  HTML main-content extraction is outside this optional helper. Candidate generation
  validates JSON, labels every draft needs_review, and never overwrites the golden
  evaluation. Mock candidates are templates, not reviewed new evaluation facts.

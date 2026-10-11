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

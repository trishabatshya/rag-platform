"""Portable task runner: python tasks.py TARGET [additional arguments]."""

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PYTHON = sys.executable
COMMANDS = {
    "install": [[PYTHON, "-m", "pip", "install", "-r", str(ROOT / "requirements.txt")]],
    "test": [[PYTHON, "-m", "pytest"]],
    "lint": [
        [PYTHON, "-m", "ruff", "check", "."],
        [PYTHON, "-m", "ruff", "format", "--check", "."],
    ],
    "up": [["docker", "compose", "up", "-d"]],
    "down": [["docker", "compose", "down"]],
    "ingest": [[PYTHON, "-m", "app.ingest"]],
    "run": [[PYTHON, "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]],
    "eval": [[PYTHON, "-m", "eval.run_eval", "--tag", "baseline"]],
    "bench-cache": [
        [PYTHON, "-m", "eval.bench_cache_router", flag]
        for flag in ("--sweep", "--router", "--compare")
    ],
    "bench-acl": [[PYTHON, "-m", "eval.bench_acl"]],
    "bench-graph": [[PYTHON, "-m", "eval.bench_graphrag"]],
    "dashboard": [[PYTHON, "-m", "streamlit", "run", str(ROOT / "dashboard.py")]],
    "report": [[PYTHON, "-m", "scripts.make_report"]],
}


def main() -> int:
    """Run a target without a shell, preserving subprocess exit status."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", choices=COMMANDS)
    args, extra = parser.parse_known_args()
    environment = os.environ.copy()
    environment.setdefault("RAG_MODE", "mock")
    for command in COMMANDS[args.target]:
        try:
            result = subprocess.run(command + extra, cwd=ROOT, env=environment, check=False)
        except FileNotFoundError as error:
            print(f"Required executable unavailable: {error.filename}", file=sys.stderr)
            return 127
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

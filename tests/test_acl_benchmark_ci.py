"""Benchmark CLI output and the Windows/Linux offline CI workflow."""

import csv
import subprocess
import sys

import pytest
import yaml

from app.config import ROOT
from eval.bench_acl import run_benchmark


def test_acl_benchmark_cli_writes_measured_mock_rows(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tasks.py"),
            "bench-acl",
            "--output-dir",
            str(tmp_path / "ACL results"),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "MOCK (not a result)" in result.stdout
    paths = list((tmp_path / "ACL results").glob("acl_*.csv"))
    assert len(paths) == 1
    with paths[0].open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 201
    assert all(row["mode"] == "MOCK" for row in rows)
    assert all(
        float(row["with_filter_ms"]) >= 0 and float(row["without_filter_ms"]) >= 0
        for row in rows[:-1]
    )
    assert rows[-1]["measurement"] == "revoke" and float(rows[-1]["revoke_to_effect_ms"]) >= 0


def test_acl_benchmark_requires_at_least_200_pairs(tmp_path):
    with pytest.raises(ValueError, match="at least 200"):
        run_benchmark(tmp_path, 199)


def test_ci_workflow_validates_offline_windows_and_linux_checks():
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )
    assert workflow["on"] == ["push", "pull_request"]
    job = workflow["jobs"]["test"]
    assert set(job["strategy"]["matrix"]["os"]) == {"windows-latest", "ubuntu-latest"}
    assert job["env"]["RAG_MODE"] == "mock"
    assert {step["run"] for step in job["steps"] if "run" in step} == {
        "python tasks.py install",
        "python tasks.py lint",
        "python tasks.py test",
    }

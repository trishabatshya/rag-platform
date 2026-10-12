"""Export up to ten actual answer/evidence failures per system for human categorization."""

import argparse
import csv
import json
from pathlib import Path


def _cell(value: str) -> str:
    return value.replace("\\", "\\\\").replace("|", "\\|").replace("\n", "<br>")


def write_failures(csv_path: Path, output: Path, limit: int = 10) -> None:
    """Leave category cells empty; never invent failures to fill a ten-row quota."""
    if limit <= 0:
        raise ValueError("limit must be positive")
    with csv_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    lines = [
        "# GraphRAG failure review",
        "",
        f"Input: {csv_path.name}",
        "",
        "Categories: extraction miss / bad resolution / bad entity linking / "
        "reranker error / generation error. Fill the empty category cells by hand.",
        "",
    ]
    for system in ("vector", "graph_hybrid", "decomposition"):
        available = [
            r
            for r in rows
            if r["system"] == system and (float(r["em"]) < 1 or float(r["supporting_recall"]) < 1)
        ]
        selected = available[:limit]
        modes = sorted({r["mode"] for r in rows if r["system"] == system})
        lines += [
            f"## {system}",
            "",
            f"Mode: {', '.join(modes)}. "
            f"Showing {len(selected)} of {len(available)} available failures.",
            "",
            "| Question | Gold | Predicted | Retrieved titles | Failure category |",
            "| --- | --- | --- | --- | --- |",
        ]
        for row in selected:
            cells = [
                row["question"],
                row["gold"],
                row["predicted"],
                "; ".join(json.loads(row["retrieved_titles"])),
            ]
            lines.append("| " + " | ".join(_cell(c) for c in cells) + " |  |")
        lines.append("")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    """Read an actual benchmark CSV and write a reviewable markdown artifact."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path)
    parser.add_argument(
        "--output", type=Path, default=Path("eval/results/failure_analysis_project3.md")
    )
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    write_failures(args.csv_path, args.output, args.limit)
    print(args.output)


if __name__ == "__main__":
    main()

"""Export reproducible human-review samples and calculate filled-verdict agreement."""

import argparse
import csv
import random
from pathlib import Path


def sample_judgments(input_path: Path, output_path: Path, count: int = 30, seed: int = 42) -> int:
    """Sample up to count evaluation rows without overwriting existing human work."""
    if count <= 0:
        raise ValueError("Sample count must be positive")
    with input_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "correct" not in reader.fieldnames:
            raise ValueError("Input is not a judged evaluation CSV")
        fields = list(reader.fieldnames) + ["human_verdict"]
        rows = list(reader)
    chosen = random.Random(seed).sample(rows, min(count, len(rows)))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows({**row, "human_verdict": ""} for row in chosen)
    return len(chosen)


def agreement(path: Path) -> dict[str, int | float | None]:
    """Compare completed CORRECT/INCORRECT human verdicts; blanks remain unreviewed."""
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or not {"correct", "human_verdict"} <= set(reader.fieldnames):
            raise ValueError("Review CSV requires correct and human_verdict columns")
        rows = list(reader)
    matches = reviewed = 0
    for row in rows:
        human = row["human_verdict"].strip().upper()
        if not human:
            continue
        if human not in {"CORRECT", "INCORRECT"} or row["correct"] not in {"0", "1"}:
            raise ValueError("Use CORRECT or INCORRECT for human verdicts")
        reviewed += 1
        matches += int((human == "CORRECT") == (row["correct"] == "1"))
    return {
        "total": len(rows),
        "reviewed": reviewed,
        "agreement": matches / reviewed if reviewed else None,
    }


def main() -> None:
    """Export review rows or assess an already annotated review file."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--count", type=int, default=30)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--agreement", action="store_true")
    args = parser.parse_args()
    if args.agreement:
        print(agreement(args.input))
    else:
        output = args.output or args.input.with_name(args.input.stem + "_human_review.csv")
        count = sample_judgments(args.input, output, args.count, args.seed)
        print(f"Wrote {count} rows to {output}; fill human_verdict with CORRECT or INCORRECT.")


if __name__ == "__main__":
    main()

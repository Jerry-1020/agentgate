"""Enforce line and branch coverage independently for an explicit production file set."""

import argparse
import json
import re
import subprocess
from pathlib import Path


def check(data, paths, minimum):
    failures = []
    for path in paths:
        match = next(
            (
                record
                for name, record in data["files"].items()
                if name == path or name.endswith("/" + path)
            ),
            None,
        )
        if match is None:
            failures.append(f"{path}: missing coverage")
            continue
        summary = match["summary"]
        for label, covered, total in [
            ("lines", summary["covered_lines"], summary["num_statements"]),
            ("branches", summary.get("covered_branches", 0), summary.get("num_branches", 0)),
        ]:
            if total and covered / total * 100 < minimum:
                failures.append(f"{path}: {label} {covered / total * 100:.2f}% < {minimum}%")
    return failures


def check_changed_lines(data, paths, baseline, minimum):
    failures = []
    for path in paths:
        patch = subprocess.run(
            ["git", "diff", "--unified=0", baseline, "--", path],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        changed = set()
        for start, count in re.findall(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", patch):
            changed.update(range(int(start), int(start) + (int(count) if count else 1)))
        record = next(
            (r for name, r in data["files"].items() if name == path or name.endswith("/" + path)),
            None,
        )
        if record is None:
            continue  # The full-file gate reports this as a failure.
        executed, missed = set(record["executed_lines"]), set(record["missing_lines"])
        tracked = (
            subprocess.run(
                ["git", "ls-files", "--error-unmatch", "--", path], capture_output=True, check=False
            ).returncode
            == 0
        )
        relevant = (changed if tracked else executed | missed) & (executed | missed)
        if relevant and len(relevant & executed) / len(relevant) * 100 < minimum:
            failures.append(f"{path}: changed-line coverage below {minimum}%")
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coverage-json", required=True, type=Path)
    parser.add_argument("--files", required=True, type=Path)
    parser.add_argument("--baseline")
    parser.add_argument("--minimum", type=float, default=80)
    args = parser.parse_args()
    data = json.loads(args.coverage_json.read_text())
    failures = check(data, [s for s in args.files.read_text().splitlines() if s], args.minimum)
    if args.baseline:
        failures += check_changed_lines(
            data, [s for s in args.files.read_text().splitlines() if s], args.baseline, args.minimum
        )
    for failure in failures:
        print(failure)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

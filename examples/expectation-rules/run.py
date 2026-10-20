"""Replay synthetic multi-turn traces through the three built-in expectation rules."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from agentgate.application.dataset_management import DatasetManagement
from agentgate.application.evaluator_management import build_default_evaluator_management
from agentgate.domain import Trace
from agentgate.storage.sqlite import SQLiteRepository

HERE = Path(__file__).resolve().parent
EVALUATOR_IDS = ("final-state", "tool-arguments", "final-output")
EXPECTATION_IDS = {
    "review-state", "approve-state", "review-tool", "approve-tool",
    "review-output", "approve-output",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=HERE / "results.json")
    args = parser.parse_args()
    document = json.loads((HERE / "dataset.json").read_text())
    traces = json.loads((HERE / "traces.json").read_text())

    with TemporaryDirectory(prefix="agentgate-expectation-rules-") as directory:
        repository = SQLiteRepository(Path(directory) / "example.db")
        try:
            datasets = DatasetManagement(repository)
            dataset, _ = datasets.import_json(document)
            published = datasets.get_version(dataset.id, 1)
            evaluators = build_default_evaluator_management(repository)
            specs = evaluators.select(EVALUATOR_IDS)
            evaluators.validate_plan(published, specs)
            scenarios = {}
            verified = True
            for expected_outcome, payload in traces.items():
                results = evaluators.evaluate_case(
                    published.cases[0], Trace.model_validate(payload), specs
                )
                checks = [check for result in results for check in result.checks]
                verified = verified and (
                    len(results) == 3
                    and len(checks) == 6
                    and {check.expectation_id for check in checks} == EXPECTATION_IDS
                    and all(result.outcome.value == expected_outcome for result in results)
                    and all(check.outcome.value == expected_outcome for check in checks)
                )
                scenarios[expected_outcome] = [
                    {
                        **result.model_dump(mode="json", exclude={"id", "checks"}),
                        "checks": [
                            check.model_dump(mode="json", exclude={"id"})
                            for check in result.checks
                        ],
                    }
                    for result in results
                ]
            report = {
                "offline_rules_verified": verified,
                "trace_source": "synthetic",
                "dataset_id": dataset.id,
                "dataset_version": published.version,
                "dataset_content_sha256": published.content_sha256,
                "scenarios": scenarios,
            }
        finally:
            repository.close()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(f"offline_rules_verified={verified}; results={args.output}")
    return 0 if verified else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Offline checks for snapshot identity and truthful acceptance results."""

from __future__ import annotations

import copy
import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from agentgate.dataset.loader import load_dataset

SOURCE = Path(__file__).with_name("run.py")
SPEC = importlib.util.spec_from_file_location("conciseness_example", SOURCE)
example = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(example)


def fixture():
    _, version = load_dataset(example.example_dataset(), "json")
    evaluator = {
        "id": "example-judge",
        "version": "1",
        "kind": "llm_judge",
        "content_sha256": "a" * 64,
        "config": {"model": {"provider_id": "test", "model_id": "test-model"}},
    }
    manifest = {
        "dataset": version.model_dump(mode="json"),
        "selected_case_ids": ["conciseness-number"],
        "primary_evaluator_ids": [evaluator["id"]],
        "evaluator_specs": [evaluator],
        "target": {
            "adapter_type": "agent_platform_mock",
            "ref": {"external_target_id": "agent-base", "external_version_id": "1.0"},
            "invocation_config": {
                "agent_id": "agent-base",
                "runtime_type": "base",
                "simulated": True,
                "origin": "http://127.0.0.1:8119",
            },
        },
    }
    result = {
        "evaluator_id": evaluator["id"],
        "evaluator_content_sha256": evaluator["content_sha256"],
        "run_id": "original-run",
        "case_id": "conciseness-number",
        "outcome": "fail",
        "score": 0.2,
        "reason": "Contains unnecessary text.",
        "judge_record": {
            "provider_id": "test",
            "requested_model": "test-model",
            "raw_response": '{"score":0.2}',
            "request_id": "offline-fixture-request",
            "request_sha256": "b" * 64,
        },
    }
    samples = {"run": {"id": "original-run"}, "complete": True, "results": [result]}
    return manifest, evaluator, samples


class ExampleAcceptanceTests(unittest.TestCase):
    def test_fixture_has_valid_stable_content_hash(self):
        document = example.example_dataset()
        _, version = load_dataset(document, "json")
        self.assertEqual(version.content_sha256, document["version"]["content_sha256"])
        self.assertEqual(len(version.cases), 2)

    def test_resume_reads_pinned_version_without_catalog_or_model_calls(self):
        manifest, evaluator, samples = fixture()
        responses = {
            "/runs/original-run/manifest": manifest,
            "/evaluation-tasks": [{
                "id": "durable-task", "kind": "single", "run_ids": ["newer-run"],
                "previous_run_ids": ["original-run"],
            }],
            "/runs/original-run/status": {"status": "completed"},
            "/runs/original-run/samples": samples,
        }
        requests = []

        def call(path, payload=None, *, method=None):
            self.assertIsNone(payload, "resume must not write or submit work")
            self.assertIsNone(method)
            requests.append(path)
            return copy.deepcopy(responses[path])

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "results.json"
            arguments = [str(SOURCE), "--evaluator-id", evaluator["id"],
                         "--resume-run", "original-run", "--output", str(output)]
            with (patch.object(example, "api_client", return_value=call),
                  patch("sys.argv", arguments), redirect_stdout(io.StringIO())):
                self.assertEqual(example.main(), 0)
            report = json.loads(output.read_text())
        self.assertTrue(report["end_to_end_verified"])
        self.assertEqual(report["task_id"], "durable-task")
        self.assertEqual(report["evaluator_version"], "1")
        self.assertEqual(report["results"][0]["outcome"], "fail")
        self.assertFalse(any("evaluators" in path or "model-runtime" in path for path in requests))

    def test_manifest_rejects_another_dataset_agent_or_evaluator(self):
        manifest, evaluator, _ = fixture()
        for path, value in [
            (("dataset", "dataset_id"), "different-dataset"),
            (("dataset", "content_sha256"), "c" * 64),
            (("target", "adapter_type"), "inbank_chatabc"),
            (("target", "ref", "external_target_id"), "agent-workflow"),
            (("target", "invocation_config", "simulated"), False),
            (("target", "invocation_config", "origin"), "https://example.com"),
            (("primary_evaluator_ids",), ["other-judge"]),
        ]:
            with self.subTest(path=path):
                changed = copy.deepcopy(manifest)
                parent = changed
                for key in path[:-1]:
                    parent = parent[key]
                parent[path[-1]] = value
                with self.assertRaises(RuntimeError):
                    example.validate_manifest(changed, evaluator["id"])

    def test_scored_failure_is_valid_but_error_or_missing_evidence_is_not(self):
        manifest, evaluator, samples = fixture()
        ids = manifest["selected_case_ids"]
        self.assertEqual(example.result_rows(samples, evaluator, ids, "original-run")[0]["score"], 0.2)
        for change in (
            {"outcome": "error", "score": None},
            {"score": float("nan")},
            {"score": True},
            {"judge_record": {}},
            {"run_id": "other-run"},
            {"evaluator_content_sha256": "c" * 64},
        ):
            with self.subTest(change=change):
                changed = copy.deepcopy(samples)
                changed["results"][0].update(change)
                with self.assertRaises(RuntimeError):
                    example.result_rows(changed, evaluator, ids, "original-run")


if __name__ == "__main__":
    unittest.main()

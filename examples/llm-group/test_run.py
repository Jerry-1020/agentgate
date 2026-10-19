"""Offline checks for the example's success criteria; no network or model calls."""

import copy
import unittest

from run import verify_results


class ResultVerification(unittest.TestCase):
    def setUp(self):
        self.manifest = {
            "primary_evaluator_ids": ["parent"],
            "selected_case_ids": ["case"],
            "evaluator_specs": [
                {
                    "id": "parent",
                    "version": "1",
                    "kind": "llm_group",
                    "children": [
                        {"evaluator_id": "a", "evaluator_version": "1", "weight": 0.4},
                        {"evaluator_id": "b", "evaluator_version": "2", "weight": 0.6},
                    ],
                },
                *[
                    {"id": key, "version": version, "config": {"model": {"model_id": "test-model"}}}
                    for key, version in [("a", "1"), ("b", "2")]
                ],
            ],
        }
        self.samples = {
            "complete": True,
            "run": {"status": "completed"},
            "results": [
                {
                    "case_id": "case",
                    "evaluator_id": "parent",
                    "evaluator_version": "1",
                    "score": 0.7,
                    "outcome": "fail",
                },
                *[
                    {
                        "case_id": "case",
                        "evaluator_id": identity,
                        "evaluator_name": identity,
                        "evaluator_version": version,
                        "score": score,
                        "outcome": outcome,
                        "checks": [{"reason": "Grounded assessment"}],
                        "judge_record": {
                            "raw_response": "real response",
                            "request_sha256": identity * 64,
                            "provider_id": "test",
                            "requested_model": "test-model",
                        },
                    }
                    for identity, version, score, outcome in [
                        ("a", "1", 1, "pass"),
                        ("b", "2", 0.5, "fail"),
                    ]
                ],
            ],
        }

    def test_scores_below_threshold_still_count_as_successful_execution(self):
        result = verify_results(self.manifest, self.samples, "parent")
        self.assertEqual(result["score"], 0.7)
        self.assertEqual(result["outcome"], "fail")
        self.assertEqual(len(result["children"]), 2)

    def test_child_error_wrong_version_or_missing_call_evidence_is_rejected(self):
        for change in (
            {"outcome": "error", "score": None},
            {"evaluator_version": "3"},
            {"judge_record": {}},
        ):
            samples = copy.deepcopy(self.samples)
            samples["results"][1].update(change)
            with self.assertRaises(ValueError):
                verify_results(self.manifest, samples, "parent")

    def test_wrong_aggregation_and_incomplete_run_are_rejected(self):
        self.samples["results"][0]["score"] = 0.9
        with self.assertRaises(ValueError):
            verify_results(self.manifest, self.samples, "parent")
        self.samples["results"][0]["score"] = 0.7
        self.samples["complete"] = False
        with self.assertRaises(ValueError):
            verify_results(self.manifest, self.samples, "parent")

    def test_changed_parent_version_or_model_is_rejected(self):
        for result_index, field, value in [
            (0, "evaluator_version", "2"),
            (
                1,
                "judge_record",
                {
                    "raw_response": "response",
                    "request_sha256": "request",
                    "requested_model": "wrong-model",
                },
            ),
        ]:
            samples = copy.deepcopy(self.samples)
            samples["results"][result_index][field] = value
            with self.assertRaises(ValueError):
                verify_results(self.manifest, samples, "parent")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import unittest

from game_pipeline import build_game_logic_design, normalize_game_spec
from game_pipeline.game_failure_classifier import classify_failure
from game_pipeline.game_quality import evaluate_game_quality, parse_playtest_metrics
from game_pipeline.unity_project_validator import UnityValidationOutcome


class GameQualityTest(unittest.TestCase):
    def test_parses_runtime_metrics_and_scores_complete_platformer(self) -> None:
        design = build_game_logic_design(
            normalize_game_spec("플랫포머", {"mechanics": ["movement", "jump"]})
        )
        payload = {
            "completed": True,
            "elapsed_seconds": 4.2,
            "deaths": 1,
            "stuck_seconds": 0,
            "last_reached_zone": "mastery",
            "failed_transition": "",
            "unused_requested_features": [],
            "passed_scenarios": ["feature_binding", "checkpoint_recovery", "start_to_goal"],
        }
        log = "UNITY_PLAYTEST_METRICS:" + json.dumps(payload)
        report = evaluate_game_quality(design, log)

        self.assertTrue(report["passed"])
        self.assertEqual(report["score"], 100)
        self.assertEqual(parse_playtest_metrics(log)["last_reached_zone"], "mastery")

    def test_classifies_binding_failure_separately_from_compile_failure(self) -> None:
        binding = UnityValidationOutcome(
            issues=[
                {
                    "code": "UNITY_RUNTIME_TEST_FAILED",
                    "severity": "error",
                    "message": "runtime.required_feature_unbound: air_dash",
                }
            ]
        )
        compile_error = UnityValidationOutcome(
            issues=[
                {
                    "code": "UNITY_BATCH_VALIDATION_FAILED",
                    "severity": "error",
                    "message": "error CS0246: missing type",
                }
            ]
        )

        self.assertEqual(classify_failure(binding)["target"], "binding")
        self.assertEqual(classify_failure(compile_error)["target"], "code")


if __name__ == "__main__":
    unittest.main()

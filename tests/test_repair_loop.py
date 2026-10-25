import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from game_pipeline.feature_contract import build_feature_contract
from game_pipeline.repair_loop import _rename_with_retry, validate_and_repair
from game_pipeline.unity_project_validator import UnityValidationOutcome


def failure(code, message):
    return UnityValidationOutcome(
        checks=[{"criterion_id": "test", "passed": False, "message": message}],
        issues=[{"code": code, "severity": "error", "message": message}],
        unity_log=message,
    )


class RepairLoopTest(unittest.TestCase):
    def test_failed_project_backup_retries_windows_handle_contention(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "unity_project"
            backup = Path(directory) / "unity_project_failed_attempt_0"
            root.mkdir()
            original_rename = Path.rename
            calls = 0

            def flaky_rename(source, target):
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise PermissionError(32, "file is in use")
                return original_rename(source, target)

            with (
                patch.object(Path, "rename", autospec=True, side_effect=flaky_rename),
                patch("game_pipeline.repair_loop.time.sleep"),
            ):
                _rename_with_retry(root, backup, timeout_seconds=1)

            self.assertEqual(calls, 2)
            self.assertTrue(backup.is_dir())

    def run_loop(self, outcomes, max_repairs=2):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "game/unity_project"
            root.mkdir(parents=True)
            generation = SimpleNamespace(
                project_root=root, entry_scene=root / "Assets/Scenes/Bootstrap.unity"
            )
            design = {
                "contract_version": "3.4.0",
                "game_spec": {"asset_requirements": []},
                "generated_modules": [{"module_id": "example"}],
            }
            generator = MagicMock()

            def regenerate(*args, **kwargs):
                root.mkdir()
                return generation

            generator.generate.side_effect = regenerate
            feature_generator = MagicMock()
            feature_generator.repair.return_value = design["generated_modules"]
            record = MagicMock()
            with patch("game_pipeline.repair_loop.UnityProjectValidator") as validator:
                validator.return_value.validate.side_effect = outcomes
                try:
                    result = validate_and_repair(
                        design=design,
                        generation=generation,
                        request={
                            "image_style": "Pixel Art",
                            "mood_style": "Fantasy",
                            "viewpoint": "사이드뷰",
                            "custom_image": None,
                        },
                        generator=generator,
                        feature_generator=feature_generator,
                        record=record,
                        max_repairs=max_repairs,
                    )
                except RuntimeError:
                    result = None
                return result, feature_generator, record

    def test_compile_and_runtime_failures_are_fed_back_then_revalidated(self):
        result, model, record = self.run_loop(
            [
                failure("UNITY_BATCH_VALIDATION_FAILED", "error CS0246: unknown type"),
                failure("UNITY_RUNTIME_TEST_FAILED", "runtime.horizontal_movement FAILED"),
                UnityValidationOutcome(),
            ]
        )
        self.assertIsNotNone(result)
        self.assertEqual(model.repair.call_count, 2)
        self.assertGreaterEqual(record.call_count, 5)
        self.assertIn("CS0246", model.repair.call_args_list[0].args[1]["diagnostics"])
        self.assertIn("runtime.horizontal", model.repair.call_args_list[1].args[1]["diagnostics"])

    def test_infrastructure_failure_does_not_spend_model_calls(self):
        result, model, _ = self.run_loop([failure("UNITY_EDITOR_NOT_FOUND", "missing")])
        self.assertIsNone(result)
        model.repair.assert_not_called()

    def test_scene_failure_without_generated_code_does_not_call_model(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "game/unity_project"
            root.mkdir(parents=True)
            generation = SimpleNamespace(
                project_root=root,
                entry_scene=root / "Assets/Scenes/Bootstrap.unity",
            )
            feature_generator = MagicMock()
            with patch("game_pipeline.repair_loop.UnityProjectValidator") as validator:
                validator.return_value.validate.return_value = failure(
                    "UNITY_RUNTIME_TEST_FAILED",
                    "start_to_goal failed",
                )
                with self.assertRaisesRegex(RuntimeError, "no generated feature code"):
                    validate_and_repair(
                        design={
                            "contract_version": "3.4.0",
                            "game_spec": {"asset_requirements": []},
                            "generated_modules": [],
                        },
                        generation=generation,
                        request={},
                        generator=MagicMock(),
                        feature_generator=feature_generator,
                        record=MagicMock(),
                    )

            feature_generator.repair.assert_not_called()

    def test_repair_budget_is_bounded(self):
        result, model, _ = self.run_loop([failure("UNITY_RUNTIME_TEST_FAILED", "FAILED")] * 3)
        self.assertIsNone(result)
        self.assertEqual(model.repair.call_count, 2)

    def test_undefined_tag_error_is_preserved_for_model_feedback(self):
        result, model, _ = self.run_loop(
            [
                failure(
                    "UNITY_RUNTIME_TEST_FAILED",
                    "runtime.exception: Tag: Enemy is not defined. CompareTag",
                ),
                UnityValidationOutcome(),
            ]
        )

        self.assertIsNotNone(result)
        diagnostics = model.repair.call_args.args[1]["diagnostics"]
        self.assertIn("Tag: Enemy is not defined", diagnostics)

    def test_contract_contains_real_api_and_test_limits(self):
        contract = build_feature_contract()
        self.assertIn(
            "GetModule<T>", contract["runtime_api_sources"]["GeneratedFeatureBindingContext"]
        )
        self.assertIn("not_covered", contract["acceptance"])


if __name__ == "__main__":
    unittest.main()

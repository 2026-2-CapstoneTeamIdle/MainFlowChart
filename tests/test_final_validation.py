from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from game_pipeline.game_quality_validator_ai import GameQualityValidatorAI
from game_pipeline.unity_project_validator import UnityValidationOutcome
from mainflow.ArtifactManager import ArtifactManager
from mainflow.contracts import CONTRACT_VERSION
from mainflow.nodes.final_validation import final_validation_node


class FinalValidationTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.manager = ArtifactManager(self.temporary.name)
        self.project = self.manager.create_project()
        self.state = {"project_id": self.project}
        self.counter = 0
        self.root = Path("game/unity_project")
        self.write_project("ProjectSettings/ProjectVersion.txt", b"m_EditorVersion: 6000.0.71f1")
        self.asset = self.manager.write_bytes(
            self.project, "sound", "processed/jump.wav", b"corrected-audio", producer="test"
        )
        self.unity_path = "Assets/GameTemplate/Generated/AppliedAssets/Sounds/jump.wav"
        self.write_project(self.unity_path, b"corrected-audio")
        self.write_project(
            "Assets/GameTemplate/Generated/Design/validation_plan.json",
            json.dumps(
                {
                    "scenarios": [
                        {"scenario_id": "feature_binding"},
                        {"scenario_id": "start_to_goal"},
                    ],
                    "required_feature_bindings": ["platformer_movement"],
                }
            ).encode(),
        )
        self.manifest = {
            "entries": [
                {
                    "asset_id": "jump",
                    "asset_type": "sound",
                    "unity_path": self.unity_path,
                    "unity_binding_key": "audio:jump",
                    "required": True,
                }
            ],
            "missing_required_asset_ids": [],
        }
        self.manifest_ref = self.manager.write_json(
            self.project, "game", "bindings.json", self.manifest, producer="test"
        )
        self.write_project(
            "Assets/GameTemplate/Generated/AssetBindingManifest.json",
            json.dumps(self.manifest).encode(),
        )
        self.package = self.manager.write_bytes(
            self.project, "game", "initial.zip", b"package", producer="test"
        )
        self.put(
            "integrated_game",
            {
                "status": "integrated",
                "entry_artifact": self.package,
                "game_artifacts": [self.package, self.manifest_ref],
                "asset_binding_manifest": self.manifest_ref,
                "applied_image_asset_ids": [],
                "applied_sound_asset_ids": ["jump"],
            },
        )
        self.put(
            "logic_analysis",
            {
                "genre": "플랫포머",
                "features": [
                    {
                        "feature_id": "jump",
                        "name": "점프",
                        "description": "jump",
                        "source_text": "jump",
                    }
                ],
                "criteria": [
                    {
                        "criterion_id": "logic-jump",
                        "target": "game",
                        "description": "jump",
                        "required": True,
                    },
                    {
                        "criterion_id": "sound-mood",
                        "target": "sound",
                        "description": "mood",
                        "required": True,
                    },
                ],
            },
        )
        self.put("parsed_request", {})
        self.put(
            "game_logic_draft",
            {"required_image_asset_ids": [], "required_sound_asset_ids": ["jump"]},
        )
        for target in ("game", "image", "sound"):
            result = {"status": "passed", "checks": [], "issues": []}
            if target != "game":
                result.update(
                    validated_asset_ids=["jump"] if target == "sound" else [],
                    validated_assets={
                        "manifest_version": "1.0.0",
                        "contract_version": CONTRACT_VERSION,
                        "assets": [
                            {
                                "asset_id": "jump",
                                "asset_type": "sound",
                                "unity_binding_key": "audio:jump",
                                "artifact": self.asset,
                                "file_format": "wav",
                            }
                        ]
                        if target == "sound"
                        else [],
                    },
                )
            if target == "sound":
                result["checks"] = [
                    {"criterion_id": "sound-mood", "passed": True, "message": "fixture evidence"}
                ]
            self.put(target + "_validation_result", result)
        self.report = {
            key: ["jump"]
            for key in ("scene_bound_asset_ids", "imported_asset_ids", "registry_asset_ids")
        }
        self.outcome = UnityValidationOutcome(
            checks=[{"criterion_id": "unity.runtime_smoke", "passed": True, "message": "fixture"}],
            unity_log=(
                'UNITY_PLAYTEST_METRICS:{"completed":true,'
                '"passed_scenarios":["feature_binding","start_to_goal"],'
                '"passed_transitions":['
                '"platformer.collectible_to_progress",'
                '"platformer.hazard_to_health",'
                '"platformer.fall_to_checkpoint",'
                '"platformer.requirements_to_clear"]}'
            ),
        )

    def put(self, key, payload):
        self.counter += 1
        self.state[key] = self.manager.write_json(
            self.project,
            "data",
            key + str(self.counter) + ".json",
            {"contract_version": CONTRACT_VERSION, **payload},
            producer="test",
        )

    def write_project(self, path, content):
        target = self.manager.resolve_project_path(self.project, self.root / path)
        self.manager.write_project_file(
            self.project,
            self.root / path,
            content,
            expected_sha256=hashlib.sha256(target.read_bytes()).hexdigest()
            if target.is_file()
            else None,
        )

    def run_final(self, *, artifact_variant=""):
        def validate(*args):
            self.write_project(
                "Assets/GameTemplate/Generated/AssetBindingReport.json",
                json.dumps(self.report).encode(),
            )
            return self.outcome

        with (
            patch("mainflow.nodes.final_validation.ArtifactManager", return_value=self.manager),
            patch("mainflow.nodes.final_validation.UnityProjectValidator") as validator,
        ):
            validator.return_value.validate.side_effect = validate
            reference = final_validation_node(self.state, artifact_variant=artifact_variant)[
                "final_validation_result"
            ]
        self.assertEqual(validator.call_args.kwargs["mode"], "required")
        return self.manager.read_json(reference)

    def test_selection_matches_json_schema(self):
        import jsonschema

        schema = json.loads(
            Path("schemas/validated_asset_manifest.schema.json").read_text(encoding="utf-8")
        )
        selection = self.manager.read_json(self.state["sound_validation_result"])[
            "validated_assets"
        ]
        jsonschema.validate(selection, schema)
        del selection["assets"][0]["artifact"]
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(selection, schema)

    def test_legacy_validation_without_selection_cannot_pass(self):
        payload = self.manager.read_json(self.state["sound_validation_result"])
        del payload["validated_assets"]
        self.put("sound_validation_result", payload)
        with patch("mainflow.nodes.final_validation.ArtifactManager", return_value=self.manager):
            result = self.manager.read_json(
                final_validation_node(self.state)["final_validation_result"]
            )
        self.assertEqual(result["status"], "failed")

    def test_pass_packages_post_validation_files_and_evidence(self):
        result = self.run_final()
        self.assertEqual(result["status"], "passed")
        self.assertEqual(len(result["evidence"]), 2)
        with zipfile.ZipFile(
            io.BytesIO(self.manager.read_bytes(result["entry_artifact"]))
        ) as archive:
            self.assertEqual(archive.read("UnityProject/" + self.unity_path), b"corrected-audio")
            self.assertIn(
                "UnityProject/Assets/GameTemplate/Generated/AssetBindingReport.json",
                archive.namelist(),
            )

    def test_agent_project_packages_only_after_final_validation(self):
        integrated = self.manager.read_json(self.state["integrated_game"])
        integrated["entry_artifact"] = None
        integrated["game_artifacts"] = [self.manifest_ref]
        self.put("integrated_game", integrated)

        result = self.run_final()

        self.assertEqual(result["status"], "passed")
        self.assertIsNotNone(result["entry_artifact"])

    def test_failed_feature_audit_repairs_and_revalidates_before_pass(self):
        logic = self.manager.read_json(self.state["logic_analysis"])
        logic["features"] = [
            {
                "feature_id": "custom",
                "name": "Custom action",
                "description": "Observable action",
                "source_text": "Observable action",
            }
        ]
        logic["criteria"][0] = {
            "criterion_id": "logic-custom",
            "target": "game",
            "description": "Observable action changes the world",
            "required": True,
        }
        self.put("logic_analysis", logic)
        failed = {
            "logic-custom": {
                "satisfied": False,
                "evidence": [],
                "reason": "Action has no effect",
                "verification_status": "unsatisfied",
            }
        }
        passed = {
            "logic-custom": {
                "satisfied": True,
                "evidence": [{"path": "Assets/Runtime/Game.cs", "quote": "Observable action"}],
                "reason": "Implemented",
                "verification_status": "verified",
            }
        }
        with (
            patch.dict(
                os.environ,
                {"MAINFLOW_GAME_BUILDER": "codex_cli", "MAINFLOW_FINAL_FEATURE_AUDIT_REPAIRS": "1"},
            ),
            patch(
                "mainflow.nodes.final_validation.audit_feature_evidence",
                side_effect=[failed, passed],
            ) as audit,
            patch(
                "mainflow.nodes.final_validation.repair_feature_audit_with_configured_agent",
                return_value=UnityValidationOutcome(),
            ) as repair,
        ):
            result = self.run_final()
        self.assertEqual(result["status"], "passed")
        self.assertEqual(audit.call_count, 2)
        repair.assert_called_once()

    def test_inconclusive_citation_does_not_block_real_feature_repair(self):
        logic = self.manager.read_json(self.state["logic_analysis"])
        logic["features"] = [
            {
                "feature_id": "first",
                "name": "First",
                "description": "First behavior",
                "source_text": "First behavior",
            },
            {
                "feature_id": "second",
                "name": "Second",
                "description": "Second behavior",
                "source_text": "Second behavior",
            },
        ]
        logic["criteria"] = [
            {
                "criterion_id": f"logic-{feature_id}",
                "target": "game",
                "description": f"{feature_id} behavior works",
                "required": True,
            }
            for feature_id in ("first", "second")
        ]
        self.put("logic_analysis", logic)
        first_audit = {
            "logic-first": {
                "satisfied": False,
                "evidence": [],
                "reason": "Source quote did not match",
                "verification_status": "evidence_invalid",
            },
            "logic-second": {
                "satisfied": False,
                "evidence": [],
                "reason": "Behavior is missing",
                "verification_status": "unsatisfied",
            },
        }
        second_audit = {
            criterion_id: {
                "satisfied": True,
                "evidence": [{"path": "Assets/Runtime/Game.cs", "quote": "Behavior works"}],
                "reason": "Implemented",
                "verification_status": "verified",
            }
            for criterion_id in first_audit
        }
        with (
            patch.dict(
                os.environ,
                {"MAINFLOW_GAME_BUILDER": "codex_cli", "MAINFLOW_FINAL_FEATURE_AUDIT_REPAIRS": "1"},
            ),
            patch(
                "mainflow.nodes.final_validation.audit_feature_evidence",
                side_effect=[first_audit, second_audit],
            ) as audit,
            patch(
                "mainflow.nodes.final_validation.repair_feature_audit_with_configured_agent",
                return_value=UnityValidationOutcome(),
            ) as repair,
        ):
            result = self.run_final()
        self.assertEqual(result["status"], "passed")
        self.assertEqual(audit.call_count, 2)
        self.assertEqual(
            [item["criterion_id"] for item in repair.call_args.kwargs["findings"]],
            ["logic-second"],
        )

    def test_inconclusive_citation_alone_does_not_trigger_code_repair(self):
        logic = self.manager.read_json(self.state["logic_analysis"])
        logic["features"] = [
            {
                "feature_id": "custom",
                "name": "Custom",
                "description": "Observable behavior",
                "source_text": "Observable behavior",
            }
        ]
        logic["criteria"] = [
            {
                "criterion_id": "logic-custom",
                "target": "game",
                "description": "Observable behavior works",
                "required": True,
            }
        ]
        self.put("logic_analysis", logic)
        with (
            patch.dict(os.environ, {"MAINFLOW_GAME_BUILDER": "codex_cli"}),
            patch("mainflow.nodes.final_validation.audit_feature_evidence") as audit,
            patch(
                "mainflow.nodes.final_validation.repair_feature_audit_with_configured_agent"
            ) as repair,
        ):
            audit.return_value = {
                "logic-custom": {
                    "satisfied": False,
                    "evidence": [],
                    "reason": "Source quote did not match",
                    "verification_status": "evidence_invalid",
                }
            }
            result = self.run_final()
        self.assertEqual(result["status"], "failed")
        repair.assert_not_called()

    def test_execution_stability_uses_unity_results_instead_of_source_audit(self):
        logic = self.manager.read_json(self.state["logic_analysis"])
        logic["features"] = [
            {
                "feature_id": "stability",
                "name": "Execution stability",
                "description": "No compile errors or runtime exceptions",
                "source_text": "컴파일 오류와 반복적인 런타임 예외가 없어야 한다",
                "implementation_kind": "design_constraint",
            }
        ]
        logic["criteria"][0] = {
            "criterion_id": "logic-stability",
            "target": "game",
            "description": "No compile errors or repeated runtime exceptions",
            "required": True,
        }
        self.put("logic_analysis", logic)
        self.outcome.checks.append(
            {"criterion_id": "unity.batchmode", "passed": True, "message": "Compiled"}
        )
        with (
            patch.dict(os.environ, {"MAINFLOW_GAME_BUILDER": "codex_cli"}),
            patch("mainflow.nodes.final_validation.audit_feature_evidence") as audit,
        ):
            result = self.run_final()
        self.assertEqual(result["status"], "passed")
        audit.assert_not_called()

        self.outcome.unity_log += "\n--- PLAY MODE ---\nNullReferenceException: missing player"
        with patch.dict(os.environ, {"MAINFLOW_GAME_BUILDER": "pipeline"}):
            failed = self.run_final(artifact_variant="runtime_exception")
        self.assertEqual(failed["status"], "failed")

    def test_post_quality_validation_repackages_repaired_source(self):
        source_path = "Assets/GameTemplate/Runtime/QualityPatch.cs"
        self.write_project(source_path, b"original")
        original = self.run_final()
        self.write_project(source_path, b"repaired")

        refreshed = self.run_final(artifact_variant="post_quality")

        with zipfile.ZipFile(
            io.BytesIO(self.manager.read_bytes(original["entry_artifact"]))
        ) as archive:
            self.assertEqual(archive.read("UnityProject/" + source_path), b"original")
        with zipfile.ZipFile(
            io.BytesIO(self.manager.read_bytes(refreshed["entry_artifact"]))
        ) as archive:
            self.assertEqual(archive.read("UnityProject/" + source_path), b"repaired")
        self.assertTrue(
            refreshed["entry_artifact"]["relative_path"].endswith(
                "validated_unity_project_post_quality.zip"
            )
        )

    def test_unproven_subjective_sound_mood_is_nonblocking(self):
        payload = self.manager.read_json(self.state["sound_validation_result"])
        payload["checks"] = []
        self.put("sound_validation_result", payload)
        result = self.run_final()
        self.assertEqual(result["status"], "passed")
        self.assertIsNotNone(result["entry_artifact"])
        self.assertFalse(
            next(c for c in result["checks"] if c["criterion_id"] == "sound-mood")["passed"]
        )

    def test_agent_source_audit_can_supply_missing_feature_evidence(self):
        logic = self.manager.read_json(self.state["logic_analysis"])
        logic["features"].append(
            {
                "feature_id": "user-feature-01",
                "name": "Unique behavior",
                "description": "A custom gameplay rule",
                "source_text": "custom rule",
            }
        )
        logic["criteria"].append(
            {
                "criterion_id": "logic-user-feature-01",
                "target": "game",
                "description": "A custom gameplay rule runs",
                "required": True,
            }
        )
        self.put("logic_analysis", logic)
        with (
            patch.dict(os.environ, {"MAINFLOW_GAME_BUILDER": "codex_cli"}),
            patch("mainflow.nodes.final_validation.audit_feature_evidence") as audit,
        ):
            audit.return_value = {
                "logic-user-feature-01": {
                    "satisfied": True,
                    "evidence": [
                        {"path": "Assets/Runtime/Custom.cs", "quote": "ApplyCustomRule();"}
                    ],
                    "reason": "Bound and executed",
                }
            }
            result = self.run_final()
        self.assertEqual(result["status"], "passed")
        self.assertTrue(
            next(
                item for item in result["checks"] if item["criterion_id"] == "logic-user-feature-01"
            )["passed"]
        )
        self.assertEqual(audit.call_args.kwargs["builder"], "codex_cli")

    def test_disabled_visual_validation_waives_only_visual_style_evidence(self):
        logic = self.manager.read_json(self.state["logic_analysis"])
        logic["criteria"].append(
            {
                "criterion_id": "visual-style",
                "target": "image",
                "description": "Pixel Art visual style",
                "required": True,
            }
        )
        self.put("logic_analysis", logic)
        self.put("visual_validation_result", {"mode": "disabled", "status": "skipped"})

        result = self.run_final()

        self.assertEqual(result["status"], "passed")
        style = next(c for c in result["checks"] if c["criterion_id"] == "visual-style")
        self.assertTrue(style["passed"])
        self.assertIn("visual validation disabled", style["message"])

    def test_failed_visual_validation_still_fails_final_validation(self):
        logic = self.manager.read_json(self.state["logic_analysis"])
        logic["criteria"].append(
            {
                "criterion_id": "visual-style",
                "target": "image",
                "description": "Pixel Art visual style",
                "required": True,
            }
        )
        self.put("logic_analysis", logic)
        self.put("visual_validation_result", {"mode": "enabled", "status": "failed"})

        result = self.run_final()

        self.assertEqual(result["status"], "failed")
        self.assertFalse(
            next(c for c in result["checks"] if c["criterion_id"] == "visual-style")["passed"]
        )

    def test_procedural_sound_waives_provider_dependent_mood_evidence(self):
        payload = self.manager.read_json(self.state["sound_validation_result"])
        payload["checks"] = []
        payload["fallback_asset_ids"] = ["jump"]
        self.put("sound_validation_result", payload)

        result = self.run_final()

        self.assertEqual(result["status"], "passed")
        sound_mood = next(
            check for check in result["checks"] if check["criterion_id"] == "sound-mood"
        )
        self.assertTrue(sound_mood["passed"])
        self.assertIn("no real asset provider", sound_mood["message"])

    def test_required_asset_missing_fails(self):
        payload = self.manager.read_json(self.state["game_logic_draft"])
        payload["required_image_asset_ids"] = ["missing"]
        self.put("game_logic_draft", payload)
        self.assertEqual(self.run_final()["status"], "failed")

    def test_corrected_file_must_match_applied_bytes(self):
        self.write_project(self.unity_path, b"original-unprocessed-audio")
        self.assertEqual(self.run_final()["status"], "failed")

    def test_import_without_scene_binding_fails(self):
        self.report["scene_bound_asset_ids"] = []
        self.assertEqual(self.run_final()["status"], "failed")

    def test_staged_character_sheet_requires_animator_binding(self):
        image_path = "Assets/GameTemplate/Generated/AppliedAssets/Images/player_sprite.png"
        image_artifact = self.manager.write_bytes(
            self.project, "image", "player.png", b"player-image", producer="test"
        )
        self.write_project(image_path, b"player-image")
        manifest = {
            **self.manifest,
            "entries": [
                *self.manifest["entries"],
                {
                    "asset_id": "player_sprite",
                    "asset_type": "image",
                    "unity_path": image_path,
                    "unity_binding_key": "asset_registry:player_sprite",
                    "animation_metadata_path": (
                        "Assets/GameTemplate/Generated/AppliedAssets/Animations/player_sprite_sheet.json"
                    ),
                },
            ],
        }
        manifest_ref = self.manager.write_json(
            self.project, "game", "animated_bindings.json", manifest, producer="test"
        )
        self.write_project(
            "Assets/GameTemplate/Generated/AssetBindingManifest.json",
            json.dumps(manifest).encode(),
        )
        integrated = self.manager.read_json(self.state["integrated_game"])
        integrated["asset_binding_manifest"] = manifest_ref
        integrated["applied_image_asset_ids"] = ["player_sprite"]
        self.put("integrated_game", integrated)
        image_result = self.manager.read_json(self.state["image_validation_result"])
        image_result["validated_asset_ids"] = ["player_sprite"]
        image_result["validated_assets"]["assets"] = [
            {
                "asset_id": "player_sprite",
                "asset_type": "image",
                "unity_binding_key": "asset_registry:player_sprite",
                "artifact": image_artifact,
                "file_format": "png",
            }
        ]
        self.put("image_validation_result", image_result)
        self.report = {
            key: ["jump", "player_sprite"]
            for key in ("scene_bound_asset_ids", "imported_asset_ids", "registry_asset_ids")
        }
        result = self.run_final()
        animation_check = next(
            item
            for item in result["checks"]
            if item["criterion_id"] == "integration.character_animation_bindings"
        )
        self.assertFalse(animation_check["passed"])

    def test_unity_unavailable_or_runtime_disabled_fails(self):
        self.outcome = UnityValidationOutcome(
            checks=[{"criterion_id": "unity.batchmode", "passed": False, "message": "missing"}],
            issues=[{"code": "UNITY_EDITOR_NOT_FOUND", "severity": "error", "message": "missing"}],
        )
        self.assertEqual(self.run_final()["status"], "failed")

    def test_runtime_disabled_cannot_pass(self):
        self.outcome = UnityValidationOutcome()
        self.assertEqual(self.run_final()["status"], "failed")

    def test_missing_start_to_goal_fails(self):
        self.outcome.unity_log = (
            'UNITY_PLAYTEST_METRICS:{"completed":true,"passed_scenarios":["feature_binding"],'
            '"passed_transitions":["platformer.collectible_to_progress",'
            '"platformer.hazard_to_health","platformer.fall_to_checkpoint",'
            '"platformer.requirements_to_clear"]}'
        )
        self.assertEqual(self.run_final()["status"], "failed")

    def test_missing_causal_transition_fails(self):
        self.outcome.unity_log = (
            'UNITY_PLAYTEST_METRICS:{"completed":true,'
            '"passed_scenarios":["feature_binding","start_to_goal"],'
            '"passed_transitions":["platformer.collectible_to_progress"]}'
        )

        result = self.run_final()

        self.assertEqual(result["status"], "failed")
        causal = next(
            check for check in result["checks"] if check["criterion_id"] == "final.causal_gameplay"
        )
        self.assertFalse(causal["passed"])
        self.assertIn("platformer.requirements_to_clear", causal["message"])

    def test_partial_upstream_failure_cannot_pass(self):
        payload = self.manager.read_json(self.state["sound_validation_result"])
        payload["status"] = "needs_revision"
        self.put("sound_validation_result", payload)
        self.assertEqual(self.run_final()["status"], "failed")

    def test_reconciled_game_validation_reaches_quality_gate(self):
        self.put(
            "game_validation_result",
            {
                "status": "failed",
                "checks": [
                    {
                        "criterion_id": "unity.runtime_smoke",
                        "passed": False,
                        "message": "earlier runtime failure",
                    }
                ],
                "issues": [
                    {
                        "code": "UNITY_RUNTIME_TEST_FAILED",
                        "severity": "error",
                        "message": "earlier runtime failure",
                    }
                ],
            },
        )
        original_reference = self.state["game_validation_result"]

        def validate(*args):
            self.write_project(
                "Assets/GameTemplate/Generated/AssetBindingReport.json",
                json.dumps(self.report).encode(),
            )
            return self.outcome

        with (
            patch("mainflow.nodes.final_validation.ArtifactManager", return_value=self.manager),
            patch("mainflow.nodes.final_validation.UnityProjectValidator") as validator,
        ):
            validator.return_value.validate.side_effect = validate
            output = final_validation_node(self.state)

        final_result = self.manager.read_json(output["final_validation_result"])
        effective = self.manager.read_json(output["game_validation_result"])
        self.assertEqual(final_result["status"], "passed")
        self.assertEqual(self.manager.read_json(original_reference)["status"], "failed")
        self.assertEqual(effective["status"], "passed")
        self.assertFalse(any(not item["passed"] for item in effective["checks"]))
        GameQualityValidatorAI._enforce_hard_evidence(  # type: ignore[arg-type]
            {"status": "passed"}, {"game_validation_result": effective}
        )

    def test_corrupt_input_returns_failure_artifact(self):
        self.state["logic_analysis"]["sha256"] = "0" * 64
        with patch("mainflow.nodes.final_validation.ArtifactManager", return_value=self.manager):
            reference = final_validation_node(self.state)["final_validation_result"]
        self.assertEqual(self.manager.read_json(reference)["status"], "failed")

    def test_stale_binding_report_is_not_evidence(self):
        self.write_project(
            "Assets/GameTemplate/Generated/AssetBindingReport.json",
            json.dumps(self.report).encode(),
        )
        with (
            patch("mainflow.nodes.final_validation.ArtifactManager", return_value=self.manager),
            patch("mainflow.nodes.final_validation.UnityProjectValidator") as validator,
        ):
            validator.return_value.validate.return_value = self.outcome
            reference = final_validation_node(self.state)["final_validation_result"]
        self.assertEqual(self.manager.read_json(reference)["status"], "failed")


if __name__ == "__main__":
    unittest.main()

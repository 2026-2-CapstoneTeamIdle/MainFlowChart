from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

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
            unity_log='UNITY_PLAYTEST_METRICS:{"completed":true,"passed_scenarios":["feature_binding","start_to_goal"]}',
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

    def run_final(self):
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
            reference = final_validation_node(self.state)["final_validation_result"]
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

    def test_unproven_semantic_criterion_fails(self):
        payload = self.manager.read_json(self.state["sound_validation_result"])
        payload["checks"] = []
        self.put("sound_validation_result", payload)
        result = self.run_final()
        self.assertEqual(result["status"], "failed")
        self.assertIsNone(result["entry_artifact"])
        self.assertFalse(
            next(c for c in result["checks"] if c["criterion_id"] == "sound-mood")["passed"]
        )

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
            'UNITY_PLAYTEST_METRICS:{"completed":true,"passed_scenarios":["feature_binding"]}'
        )
        self.assertEqual(self.run_final()["status"], "failed")

    def test_partial_upstream_failure_cannot_pass(self):
        payload = self.manager.read_json(self.state["sound_validation_result"])
        payload["status"] = "needs_revision"
        self.put("sound_validation_result", payload)
        self.assertEqual(self.run_final()["status"], "failed")

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

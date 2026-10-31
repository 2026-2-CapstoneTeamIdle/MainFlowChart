from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock, patch

from game_pipeline import (
    UnityProjectGenerator,
    UnityProjectValidator,
    build_game_logic_design,
    normalize_game_spec,
)
from mainflow.ArtifactManager import ArtifactManager
from mainflow.contracts import (
    CONTRACT_VERSION,
    GameLogicDraft,
    LogicAnalysis,
    ParsedRequest,
    ValidateGameAgentInput,
    WorkflowState,
)
from mainflow.langgraph_game_flow_skeleton import build_graph
from mainflow.nodes.validate_game import validate_game_node


class UnityProjectValidatorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.project_root = Path(self.temporary_directory.name) / "project"
        self.unity_root = self.project_root / "game" / "unity_project"
        self.request: ParsedRequest = {
            "contract_version": CONTRACT_VERSION,
            "image_style": "Pixel Art",
            "mood_style": "Fantasy",
            "genre": "플랫포머",
            "viewpoint": "사이드뷰",
            "condition": "좌우 이동과 점프가 가능한 게임",
            "custom_image": None,
        }
        design = build_game_logic_design(
            normalize_game_spec(
                "플랫포머",
                {"viewpoint": self.request["viewpoint"]},
            )
        )
        UnityProjectGenerator().generate(
            design,
            self.unity_root,
            image_style=self.request["image_style"],
            mood_style=self.request["mood_style"],
            viewpoint=self.request["viewpoint"],
        )
        self.draft: GameLogicDraft = {
            "contract_version": CONTRACT_VERSION,
            "draft_id": "platformer-game-logic-draft",
            "status": "generated",
            "engine": "Unity",
            "entry_scene": "game/unity_project/Assets/Scenes/Bootstrap.unity",
            "source_artifacts": [],
            "required_image_asset_ids": ["platformer_player", "platformer_tileset"],
            "required_sound_asset_ids": ["platformer_bgm", "jump_sfx"],
            "notes": [],
        }

    def test_static_validation_passes_generated_project(self) -> None:
        outcome = UnityProjectValidator(mode="static").validate(
            self.unity_root,
            self.draft,
            self.request,
        )

        self.assertEqual(outcome.status, "passed")
        self.assertTrue(all(check["passed"] for check in outcome.checks))
        self.assertIn(
            "UNITY_BATCHMODE_SKIPPED",
            [issue["code"] for issue in outcome.issues],
        )

    def test_failed_diagnostic_project_still_reaches_unity_validation(self) -> None:
        failed_draft = cast(GameLogicDraft, {**self.draft, "status": "failed"})

        outcome = UnityProjectValidator(mode="static").validate(
            self.unity_root,
            failed_draft,
            self.request,
            allow_failed_diagnostic=True,
        )

        self.assertEqual(outcome.status, "passed")
        self.assertIn(
            "unity.batchmode",
            [check["criterion_id"] for check in outcome.checks],
        )
        draft_check = next(
            check for check in outcome.checks if check["criterion_id"] == "game.draft"
        )
        self.assertIn("diagnostic Unity project", draft_check["message"])

    def test_asset_id_mismatch_fails_validation(self) -> None:
        request_path = (
            self.unity_root / "Assets/GameTemplate/Generated/AssetRequests/image_asset_request.json"
        )
        payload = json.loads(request_path.read_text(encoding="utf-8"))
        payload["assets"][0]["asset_id"] = "unexpected_player"
        request_path.write_text(json.dumps(payload), encoding="utf-8")

        outcome = UnityProjectValidator(mode="static").validate(
            self.unity_root,
            self.draft,
            self.request,
        )

        self.assertEqual(outcome.status, "failed")
        self.assertIn("GAME_ASSET_ID_MISMATCH", [issue["code"] for issue in outcome.issues])

    def test_required_batch_validation_checks_unity_markers(self) -> None:
        fake_editor = self.project_root / "Unity.exe"
        fake_editor.write_bytes(b"")

        def run_unity(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            log_path = Path(command[command.index("-logFile") + 1])
            log_path.write_text(
                "\n".join(
                    (
                        *UnityProjectValidator.SUCCESS_MARKERS,
                        "UNITY_RUNTIME_SMOKE_OK:",
                        "UNITY_VALIDATION_PLAN_OK:3",
                    )
                ),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(command, 0, "", "")

        with patch(
            "game_pipeline.unity_project_validator.subprocess.run",
            side_effect=run_unity,
        ):
            outcome = UnityProjectValidator(
                mode="required",
                unity_editor=fake_editor,
            ).validate(self.unity_root, self.draft, self.request)

        self.assertEqual(outcome.status, "passed")
        batch_check = next(
            check for check in outcome.checks if check["criterion_id"] == "unity.batchmode"
        )
        self.assertTrue(batch_check["passed"])

    def test_failed_batch_validation_exposes_compiler_diagnostic(self) -> None:
        fake_editor = self.project_root / "Unity.exe"
        fake_editor.write_bytes(b"")

        def run_unity(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            log_path = Path(command[command.index("-logFile") + 1])
            log_path.write_text(
                "Assets/Generated.cs(72,17): error CS0103: The name 'baseHealth' "
                "does not exist in the current context",
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(command, 1, "", "")

        with patch(
            "game_pipeline.unity_project_validator.subprocess.run",
            side_effect=run_unity,
        ):
            outcome = UnityProjectValidator(
                mode="required",
                unity_editor=fake_editor,
            ).validate(self.unity_root, self.draft, self.request)

        batch_check = next(
            check for check in outcome.checks if check["criterion_id"] == "unity.batchmode"
        )
        self.assertFalse(batch_check["passed"])
        self.assertIn("error CS0103", batch_check["message"])


class ValidateGameNodeTest(unittest.TestCase):
    def test_node_writes_passed_result_for_valid_static_project(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory) / "workspace"
            with patch.dict(
                os.environ,
                {
                    "MAINFLOW_WORKSPACE": str(workspace),
                    "MAINFLOW_UNITY_VALIDATION_MODE": "static",
                },
            ):
                manager = ArtifactManager()
                project_id = manager.create_project()
                project_root = manager.ensure_project(project_id)
                request: ParsedRequest = {
                    "contract_version": CONTRACT_VERSION,
                    "image_style": "Pixel Art",
                    "mood_style": "Fantasy",
                    "genre": "플랫포머",
                    "viewpoint": "사이드뷰",
                    "condition": "점프가 가능한 게임",
                    "custom_image": None,
                }
                design = build_game_logic_design(
                    normalize_game_spec("플랫포머", {"viewpoint": "사이드뷰"})
                )
                generation = UnityProjectGenerator().generate(
                    design,
                    project_root / "game" / "unity_project",
                    image_style=request["image_style"],
                    mood_style=request["mood_style"],
                    viewpoint=request["viewpoint"],
                )
                source_reference = manager.import_file(
                    project_id,
                    "game",
                    generation.manifest_path,
                    filename="unity_project_manifest.json",
                    producer="design_game_logic",
                    media_type="application/json",
                )
                draft: GameLogicDraft = {
                    "contract_version": CONTRACT_VERSION,
                    "draft_id": "platformer-game-logic-draft",
                    "status": "generated",
                    "engine": "Unity",
                    "entry_scene": "game/unity_project/Assets/Scenes/Bootstrap.unity",
                    "source_artifacts": [source_reference],
                    "required_image_asset_ids": [
                        asset["asset_id"]
                        for asset in design["game_spec"]["asset_requirements"]
                        if asset["asset_type"] == "image"
                    ],
                    "required_sound_asset_ids": [
                        asset["asset_id"]
                        for asset in design["game_spec"]["asset_requirements"]
                        if asset["asset_type"] == "sound"
                    ],
                    "notes": [],
                }
                logic: LogicAnalysis = {
                    "contract_version": CONTRACT_VERSION,
                    "logic_analysis_id": "logic-platformer",
                    "genre": "플랫포머",
                    "viewpoint": "사이드뷰",
                    "mood_style": "Fantasy",
                    "core_loop": "이동하고 점프한다.",
                    "features": [],
                    "criteria": [],
                }
                state = {
                    "project_id": project_id,
                    "parsed_request": manager.write_json(
                        project_id,
                        "data",
                        "parsed_request.json",
                        request,
                        producer="parse_input",
                    ),
                    "logic_analysis": manager.write_json(
                        project_id,
                        "data",
                        "logic_analysis.json",
                        logic,
                        producer="logic_analysis",
                    ),
                    "game_logic_draft": manager.write_json(
                        project_id,
                        "game",
                        "game_logic_draft.json",
                        draft,
                        producer="design_game_logic",
                    ),
                }

                output = validate_game_node(cast(ValidateGameAgentInput, state))
                result = manager.read_json(output["game_validation_result"])

                self.assertEqual(result["status"], "passed")
                self.assertGreaterEqual(len(result["checks"]), 8)


class GameFailureIsolationTest(unittest.TestCase):
    def test_one_generated_feature_failure_does_not_skip_later_features(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory) / "workspace"
            feature_generator = MagicMock()
            attempted: list[str] = []
            first_module: list[str] = []

            def generate_feature(_design, requirements):
                module_id, requirement = next(iter(requirements.items()))
                attempted.append(module_id)
                if not first_module:
                    first_module.append(module_id)
                if module_id == first_module[0]:
                    raise ValueError("simulated isolated feature failure")
                class_name = "".join(part.title() for part in module_id.split("_")) + "Module"
                source = f"// generated diagnostic source for {module_id}\n"
                return [
                    {
                        "module_id": module_id,
                        "feature_id": requirement["feature_id"],
                        "feature_description": requirement["feature_description"],
                        "class_name": class_name,
                        "source_code": source,
                        "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
                    }
                ]

            feature_generator.generate.side_effect = generate_feature
            with (
                patch.dict(
                    os.environ,
                    {
                        "MAINFLOW_WORKSPACE": str(workspace),
                        "MAINFLOW_UNITY_VALIDATION_MODE": "static",
                        "SOUND_PROVIDER": "procedural",
                        "SOUND_BGM_SECONDS": "4",
                    },
                ),
                patch(
                    "mainflow.nodes.design_game_logic.create_feature_generator_from_environment",
                    return_value=feature_generator,
                ),
            ):
                final_state = cast(
                    WorkflowState,
                    build_graph().invoke(
                        {
                            "image_style": "Pixel Art",
                            "mood_style": "Fantasy",
                            "genre": "플랫포머",
                            "viewpoint": "사이드뷰",
                            "condition": (
                                "그림자를 분리해 스위치를 누른다. 과거 움직임을 복제해 "
                                "발판을 작동한다. 포탈을 직접 배치해 목적지에 도달하는 게임"
                            ),
                        }
                    ),
                )

            with patch.dict(os.environ, {"MAINFLOW_WORKSPACE": str(workspace)}):
                manager = ArtifactManager()
                failed_design = manager.read_json(
                    next(
                        artifact
                        for artifact in manager.list_artifacts(final_state["project_id"], "game")
                        if artifact["relative_path"] == "game/failed_game_logic_design.json"
                    )
                )
                diagnostic_validation_plan = json.loads(
                    (
                        workspace
                        / final_state["project_id"]
                        / "game"
                        / "unity_project"
                        / "Assets"
                        / "GameTemplate"
                        / "Generated"
                        / "Design"
                        / "validation_plan.json"
                    ).read_text(encoding="utf-8")
                )
                diagnostic_script_directory = (
                    workspace
                    / final_state["project_id"]
                    / "game"
                    / "unity_project"
                    / "Assets"
                    / "GameTemplate"
                    / "Generated"
                    / "Scripts"
                )
                partial_repair_record = (
                    workspace
                    / final_state["project_id"]
                    / "validation"
                    / "partial_repair"
                    / "attempt_0.json"
                )

            self.assertGreaterEqual(len(set(attempted)), 2)
            self.assertEqual(attempted.count(first_module[0]), 2)
            self.assertGreater(len(failed_design["generated_modules"]), 0)
            task_statuses = {
                task["task_id"]: task["status"]
                for task in failed_design["implementation_tasks"]["tasks"]
            }
            self.assertEqual(
                task_statuses[f"generate-{first_module[0].replace('_', '-')}"],
                "failed",
            )
            self.assertIn("passed", task_statuses.values())
            self.assertNotIn(
                first_module[0],
                diagnostic_validation_plan["required_feature_bindings"],
            )
            generated_ids = {module["module_id"] for module in failed_design["generated_modules"]}
            self.assertTrue(
                generated_ids.issubset(set(diagnostic_validation_plan["required_feature_bindings"]))
            )
            generated_scripts = {path.name for path in diagnostic_script_directory.glob("*.cs")}
            self.assertEqual(
                generated_scripts,
                {f"{module['class_name']}.cs" for module in failed_design["generated_modules"]},
            )
            self.assertTrue(partial_repair_record.is_file())

    def test_repair_failure_reuses_existing_blueprint_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory) / "workspace"
            feature_generator = MagicMock()

            def generated_modules(_design, requirements):
                modules = []
                for module_id, requirement in requirements.items():
                    source = "// validation is deliberately replaced by this test\n"
                    modules.append(
                        {
                            "module_id": module_id,
                            "feature_id": requirement["feature_id"],
                            "feature_description": requirement["feature_description"],
                            "class_name": "GeneratedFeature01Module",
                            "source_code": source,
                            "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
                        }
                    )
                return modules

            feature_generator.generate.side_effect = generated_modules
            feature_generator.repair.side_effect = lambda design, _feedback: design[
                "generated_modules"
            ]
            context_reviewer = MagicMock()
            context_reviewer.review.return_value = {
                "approved": False,
                "summary": "generated module needs one contextual repair",
                "inspected_files": [
                    "game/unity_project/Assets/GameTemplate/Generated/Scripts/GeneratedFeature01Module.cs"
                ],
                "issues": [
                    {
                        "severity": "error",
                        "category": "api",
                        "relative_path": (
                            "game/unity_project/Assets/GameTemplate/Generated/Scripts/"
                            "GeneratedFeature01Module.cs"
                        ),
                        "line": 1,
                        "message": "referenced API does not match the project contract",
                        "suggested_fix": "use the binding context API",
                    }
                ],
                "provider": "fake",
                "model": "fake",
                "turns": 2,
                "tool_calls": ["list_project_files", "read_project_text"],
            }
            with (
                patch.dict(
                    os.environ,
                    {
                        "MAINFLOW_WORKSPACE": str(workspace),
                        "MAINFLOW_UNITY_VALIDATION_MODE": "static",
                    },
                ),
                patch(
                    "mainflow.nodes.design_game_logic.create_feature_generator_from_environment",
                    return_value=feature_generator,
                ),
                patch(
                    "mainflow.nodes.design_game_logic."
                    "create_project_context_reviewer_from_environment",
                    return_value=context_reviewer,
                ),
                patch(
                    "mainflow.nodes.design_game_logic.validate_and_repair",
                    side_effect=RuntimeError("simulated repair exhaustion"),
                ),
            ):
                final_state = cast(
                    WorkflowState,
                    build_graph().invoke(
                        {
                            "image_style": "Pixel Art",
                            "mood_style": "Fantasy",
                            "genre": "플랫포머",
                            "viewpoint": "사이드뷰",
                            "condition": "시간을 되돌릴 수 있는 게임",
                        }
                    ),
                )

                manager = ArtifactManager()
                game_draft = manager.read_json(final_state["game_logic_draft"])
                blueprint_artifacts = [
                    artifact
                    for artifact in manager.list_artifacts(final_state["project_id"], "game")
                    if artifact["relative_path"] == "game/game_blueprint.json"
                ]

                self.assertEqual(game_draft["status"], "failed")
                self.assertEqual(len(blueprint_artifacts), 1)
                self.assertIn("simulated repair exhaustion", " ".join(game_draft["notes"]))
                feature_generator.repair.assert_called_once()
                context_report = next(
                    artifact
                    for artifact in manager.list_artifacts(final_state["project_id"], "validation")
                    if artifact["relative_path"] == "validation/project_context_review.json"
                )
                self.assertTrue(manager.read_json(context_report)["repair_applied"])
                self.assertTrue(
                    (
                        manager.ensure_project(final_state["project_id"])
                        / "game/unity_project_before_context_repair"
                    ).is_dir()
                )

    def test_image_and_sound_branches_complete_when_game_generation_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory) / "workspace"
            with (
                patch.dict(
                    os.environ,
                    {
                        "MAINFLOW_WORKSPACE": str(workspace),
                        "MAINFLOW_UNITY_VALIDATION_MODE": "static",
                        "SOUND_PROVIDER": "procedural",
                        "SOUND_BGM_SECONDS": "4",
                    },
                ),
                patch(
                    "mainflow.nodes.design_game_logic.create_feature_generator_from_environment",
                    side_effect=RuntimeError("simulated game generation failure"),
                ),
            ):
                final_state = cast(
                    WorkflowState,
                    build_graph().invoke(
                        {
                            "image_style": "Pixel Art",
                            "mood_style": "Fantasy",
                            "genre": "플랫포머",
                            "viewpoint": "사이드뷰",
                            "condition": "시간을 되돌릴 수 있는 게임",
                        }
                    ),
                )

                manager = ArtifactManager()
                game_draft = manager.read_json(final_state["game_logic_draft"])
                game_validation = manager.read_json(final_state["game_validation_result"])
                image_request = manager.read_json(final_state["image_asset_request"])
                sound_request = manager.read_json(final_state["sound_asset_request"])
                image_draft = manager.read_json(final_state["image_draft"])
                sound_draft = manager.read_json(final_state["sound_draft"])
                image_validation = manager.read_json(final_state["image_validation_result"])
                sound_validation = manager.read_json(final_state["sound_validation_result"])
                integrated_game = manager.read_json(final_state["integrated_game"])
                final_validation = manager.read_json(final_state["final_validation_result"])

                self.assertEqual(game_draft["status"], "failed")
                self.assertIsNotNone(game_draft["entry_scene"])
                self.assertTrue(
                    (
                        manager.ensure_project(final_state["project_id"])
                        / "game/unity_project/GenerationManifest.json"
                    ).is_file()
                )
                self.assertEqual(game_validation["status"], "failed")
                self.assertIn(
                    "GAME_GENERATION_FAILED",
                    [issue["code"] for issue in game_validation["issues"]],
                )
                self.assertGreater(len(game_validation["checks"]), 1)
                self.assertIn(
                    "game.generation",
                    [check["criterion_id"] for check in game_validation["checks"]],
                )
                self.assertIn(
                    "unity.batchmode",
                    [check["criterion_id"] for check in game_validation["checks"]],
                )
                self.assertGreater(len(image_request["assets"]), 0)
                self.assertGreater(len(sound_request["assets"]), 0)
                # The image and sound branches generate every requested asset on their own.
                self.assertEqual(image_draft["status"], "generated")
                self.assertEqual(len(image_draft["assets"]), len(image_request["assets"]))
                self.assertEqual(sound_draft["status"], "generated")
                self.assertEqual(len(sound_draft["assets"]), len(sound_request["assets"]))
                self.assertEqual(integrated_game["status"], "failed")
                self.assertEqual(
                    set(integrated_game["applied_image_asset_ids"]),
                    set(image_validation["validated_asset_ids"]),
                )
                self.assertEqual(
                    set(integrated_game["applied_sound_asset_ids"]),
                    {asset["asset_id"] for asset in sound_draft["assets"]},
                )
                unity_project = (
                    manager.ensure_project(final_state["project_id"]) / "game/unity_project"
                )
                binding_manifest_path = (
                    unity_project / "Assets/GameTemplate/Generated/AssetBindingManifest.json"
                )
                self.assertTrue(binding_manifest_path.is_file())
                binding_manifest = json.loads(binding_manifest_path.read_text(encoding="utf-8"))
                for entry in binding_manifest["entries"]:
                    self.assertTrue((unity_project / entry["unity_path"]).is_file())
                self.assertTrue(
                    (
                        unity_project / "Assets/GameTemplate/Generated/GenerationRequest.json"
                    ).is_file()
                )
                self.assertTrue(
                    (
                        manager.ensure_project(final_state["project_id"])
                        / "game/diagnostic_integrated_unity_project.zip"
                    ).is_file()
                )
                self.assertEqual(final_validation["status"], "failed")


if __name__ == "__main__":
    unittest.main()

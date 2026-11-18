from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from game_pipeline.game_quality_validator_ai import GameQualityValidatorAI
from mainflow.ArtifactManager import ArtifactManager
from mainflow.nodes.game_quality_validator import (
    _normalize_duration_limitation,
    _normalize_placeholder_visual_limitation,
    _repair_and_review_quality,
    game_quality_validator_node,
)
from MCP.llm_types import LLMConversationMessage, LLMProviderResponse, LLMToolCall
from MCP.manager import MCPManager, MCPToolDefinition
from MCP.server import mcp


class QualityProvider:
    name = "fake"
    model = "independent-validator"

    def __init__(self, project_id: str) -> None:
        self.project_id = project_id
        self.calls = 0
        self.closed = False

    async def complete(
        self,
        messages: list[LLMConversationMessage],
        tools: list[MCPToolDefinition],
        *,
        system_prompt: str | None,
        temperature: float,
        require_tool: bool,
    ) -> LLMProviderResponse:
        self.calls += 1
        if self.calls == 1:
            return LLMProviderResponse(
                text="",
                tool_calls=(
                    LLMToolCall(
                        call_id="list",
                        name="list_project_files",
                        arguments={
                            "project_id": self.project_id,
                            "relative_directory": "game/unity_project",
                        },
                    ),
                    LLMToolCall(
                        call_id="read",
                        name="read_project_text",
                        arguments={
                            "project_id": self.project_id,
                            "relative_path": "game/project_context_index.json",
                        },
                    ),
                    LLMToolCall(
                        call_id="read-design",
                        name="read_project_text",
                        arguments={
                            "project_id": self.project_id,
                            "relative_path": "game/unity_project/Design.json",
                        },
                    ),
                ),
            )
        return LLMProviderResponse(
            text=json.dumps(
                {
                    "status": "passed",
                    "score": 88,
                    "summary": "The completed vertical slice satisfies the evidenced request.",
                    "requirement_coverage": [
                        {
                            "requirement": "Reach the final objective",
                            "status": "satisfied",
                            "evidence": ["final.start_to_goal"],
                        }
                    ],
                    "findings": [],
                    "strengths": ["Start-to-goal evidence is present."],
                    "limitations": ["Long-term retention was not measured."],
                    "inspected_files": [
                        "game/project_context_index.json",
                        "game/unity_project/Design.json",
                    ],
                }
            )
        )

    async def aclose(self) -> None:
        self.closed = True


class GameQualityValidatorAITest(unittest.TestCase):
    def test_disabled_visual_validation_is_not_a_hard_failure(self) -> None:
        GameQualityValidatorAI._enforce_hard_evidence(  # type: ignore[arg-type]
            {"status": "passed"},
            {"visual_validation_result": {"mode": "disabled", "status": "skipped"}},
        )
        with self.assertRaises(ValueError):
            GameQualityValidatorAI._enforce_hard_evidence(  # type: ignore[arg-type]
                {"status": "passed"},
                {"visual_validation_result": {"mode": "enabled", "status": "failed"}},
            )

    def test_disabled_visual_limitation_does_not_hide_readability_failure(self) -> None:
        report = {
            "status": "needs_revision",
            "requirement_coverage": [],
            "findings": [
                {
                    "severity": "warning",
                    "category": "evidence",
                    "message": "VLM visual validation was skipped because it is disabled",
                    "evidence": [],
                },
                {
                    "severity": "warning",
                    "category": "presentation",
                    "message": "The HUD is unreadable because labels overlap",
                    "evidence": ["Assets/UI.cs"],
                },
            ],
        }

        normalized = _normalize_placeholder_visual_limitation(  # type: ignore[arg-type]
            report,
            {"status": "passed"},
            {"mode": "disabled", "status": "skipped"},
        )

        self.assertEqual(normalized["status"], "needs_revision")
        self.assertEqual(normalized["findings"][0]["severity"], "info")
        self.assertEqual(normalized["findings"][1]["severity"], "warning")

        only_vlm = _normalize_placeholder_visual_limitation(  # type: ignore[arg-type]
            {**report, "findings": report["findings"][:1]},
            {"status": "passed"},
            {"mode": "disabled", "status": "skipped"},
        )
        self.assertEqual(only_vlm["status"], "passed")

    def test_successful_quality_repair_replaces_final_package_reference(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            manager = ArtifactManager(Path(temporary_directory) / "workspace")
            project_id = manager.create_project()
            state: dict[str, object] = {"project_id": project_id}
            for key in (
                "parsed_request",
                "logic_analysis",
                "game_logic_draft",
                "game_validation_result",
                "image_validation_result",
                "sound_validation_result",
                "integrated_game",
                "final_validation_result",
            ):
                state[key] = manager.write_json(
                    project_id,
                    "validation",
                    f"fixture_{key}.json",
                    {"status": "passed"},
                    producer="test",
                )
            refreshed = manager.write_json(
                project_id,
                "validation",
                "final_validation_result_post_quality.json",
                {"status": "passed", "entry_artifact": {"sha256": "repaired"}},
                producer="final_validation",
            )
            initial_report = {
                "status": "needs_revision",
                "findings": [
                    {
                        "severity": "warning",
                        "category": "gameplay",
                        "message": "Repair the gameplay source",
                        "evidence": ["Assets/Game.cs"],
                    }
                ],
            }
            repaired_report = {"status": "passed", "findings": []}

            with (
                patch.dict(os.environ, {"MAINFLOW_GAME_BUILDER": "codex_cli"}),
                patch(
                    "mainflow.nodes.game_quality_validator.ArtifactManager",
                    return_value=manager,
                ),
                patch(
                    "mainflow.nodes.game_quality_validator.run_codex_quality_review",
                    return_value=initial_report,
                ),
                patch(
                    "mainflow.nodes.game_quality_validator._repair_and_review_quality",
                    return_value=repaired_report,
                ),
                patch(
                    "mainflow.nodes.final_validation.final_validation_node",
                    return_value={"final_validation_result": refreshed},
                ) as final_validation,
            ):
                output = game_quality_validator_node(state)  # type: ignore[arg-type]

        self.assertEqual(output["final_validation_result"], refreshed)
        final_validation.assert_called_once()
        self.assertEqual(final_validation.call_args.kwargs["artifact_variant"], "post_quality")

    def test_placeholder_visual_gap_is_an_informational_limitation(self) -> None:
        report = {
            "status": "needs_revision",
            "requirement_coverage": [
                {
                    "requirement": "Placeholder visual validation was skipped",
                    "status": "unverifiable",
                    "evidence": [
                        "visual validation skipped because placeholder images were suppressed"
                    ],
                }
            ],
            "findings": [
                {
                    "severity": "warning",
                    "category": "visual",
                    "message": "Visual validation was skipped because placeholder images were suppressed",
                    "evidence": [],
                }
            ],
        }

        normalized = _normalize_placeholder_visual_limitation(  # type: ignore[arg-type]
            report, {"status": "passed"}
        )

        self.assertEqual(normalized["status"], "passed")
        self.assertEqual(normalized["findings"][0]["severity"], "info")

    def test_placeholder_normalization_preserves_unrelated_quality_failure(self) -> None:
        report = {
            "status": "needs_revision",
            "requirement_coverage": [],
            "findings": [
                {
                    "severity": "warning",
                    "category": "visual",
                    "message": "Visual validation skipped while placeholder art is disabled",
                    "evidence": [],
                },
                {
                    "severity": "warning",
                    "category": "gameplay",
                    "message": "Upgrade UI does not show projected combat stats",
                    "evidence": ["TowerDefenseGameController.cs"],
                },
            ],
        }

        normalized = _normalize_placeholder_visual_limitation(  # type: ignore[arg-type]
            report, {"status": "passed"}
        )

        self.assertEqual(normalized["status"], "needs_revision")
        self.assertEqual(normalized["findings"][0]["severity"], "info")
        self.assertEqual(normalized["findings"][1]["severity"], "warning")

    def test_estimated_playtime_does_not_fail_quality_review(self) -> None:
        report = {
            "status": "needs_revision",
            "summary": "Route may be shorter than the requested duration.",
            "requirement_coverage": [
                {
                    "requirement": "Normal play duration of at least 225 seconds",
                    "status": "missing",
                    "evidence": ["game/design/pacing_contract.json"],
                }
            ],
            "findings": [
                {
                    "severity": "error",
                    "category": "progression",
                    "message": "Authored pacing underfills normal-play duration",
                    "evidence": ["game/design/pacing_contract.json"],
                }
            ],
        }

        normalized = _normalize_duration_limitation(report, {"status": "passed"})

        self.assertEqual(normalized["status"], "passed")
        self.assertEqual(normalized["findings"][0]["severity"], "info")
        self.assertEqual(normalized["requirement_coverage"][0]["status"], "unverifiable")

        failed_label = _normalize_duration_limitation(
            {**report, "status": "failed"}, {"status": "passed"}
        )
        self.assertEqual(failed_label["status"], "passed")

    def test_duration_policy_preserves_health_and_timer_failures(self) -> None:
        report = {
            "status": "needs_revision",
            "summary": "Health and timer rules are broken.",
            "requirement_coverage": [],
            "findings": [
                {
                    "severity": "error",
                    "category": "progression",
                    "message": "Normal play duration appears too short",
                    "evidence": ["game/design/pacing_contract.json"],
                },
                {
                    "severity": "error",
                    "category": "gameplay",
                    "message": "Nonlethal hazard damage immediately respawns the player",
                    "evidence": [
                        "game/unity_project/Assets/GameTemplate/Runtime/Prototype/PrototypeHazard.cs"
                    ],
                },
                {
                    "severity": "error",
                    "category": "gameplay",
                    "message": "The 45-second escape timer never expires",
                    "evidence": [
                        "game/unity_project/Assets/GameTemplate/Runtime/Prototype/ClocktowerGameplayController.cs"
                    ],
                },
                {
                    "severity": "error",
                    "category": "presentation",
                    "message": "경과 플레이 시간 UI가 표시되지 않는다",
                    "evidence": [
                        "game/unity_project/Assets/GameTemplate/Runtime/Prototype/ClocktowerGameplayController.cs"
                    ],
                },
            ],
        }

        normalized = _normalize_duration_limitation(report, {"status": "passed"})

        self.assertEqual(normalized["status"], "needs_revision")
        self.assertEqual(
            [finding["severity"] for finding in normalized["findings"]],
            ["info", "error", "error", "error"],
        )

        mislabeled_pass = _normalize_duration_limitation(
            {**report, "status": "passed"}, {"status": "passed"}
        )
        self.assertEqual(mislabeled_pass["status"], "needs_revision")

    def test_quality_findings_trigger_repair_and_fresh_unity_evidence(self) -> None:
        manager = MagicMock()
        manager.ensure_project.return_value = Path("C:/synthetic/workspace")
        initial_report = {
            "status": "needs_revision",
            "findings": [
                {
                    "severity": "error",
                    "category": "gameplay",
                    "message": "Cannon splash is not applied on projectile impact",
                    "evidence": ["final.causal_gameplay"],
                },
                {
                    "severity": "error",
                    "category": "presentation",
                    "message": "The objective HUD has no live binding",
                    "evidence": ["game/design/ui_contract.json"],
                },
            ],
            "limitations": [],
        }
        evidence = {
            "game_logic_draft": {"status": "generated"},
            "parsed_request": {"condition": "Defend the base"},
        }
        harness = MagicMock()
        harness.repair_quality_findings.return_value = SimpleNamespace(
            status="passed",
            checks=[{"criterion_id": "unity.runtime_smoke", "passed": True}],
            issues=[],
            unity_log="UNITY_RUNTIME_SMOKE_OK",
        )
        with (
            patch.dict(
                os.environ,
                {"MAINFLOW_GAME_BUILDER": "codex_cli", "MAINFLOW_GAME_QUALITY_REPAIRS": "2"},
            ),
            patch("game_pipeline.codex_cli.CodexHarnessSettings.from_environment"),
            patch("game_pipeline.codex_cli.CodexGameHarness", return_value=harness),
            patch(
                "mainflow.nodes.game_quality_validator.run_codex_quality_review",
                return_value={"status": "passed", "findings": []},
            ) as review,
        ):
            result = _repair_and_review_quality("test-project", manager, evidence, initial_report)

        self.assertEqual(result["status"], "passed")
        harness.repair_quality_findings.assert_called_once()
        repaired = harness.repair_quality_findings.call_args.kwargs["findings"]
        self.assertEqual(len(repaired), 1)
        self.assertEqual(repaired[0]["category"], "gameplay")
        self.assertEqual(
            review.call_args.kwargs["evidence"]["post_quality_unity_validation"]["status"], "passed"
        )

    def test_quality_repair_uses_second_attempt_after_unity_rollback(self) -> None:
        manager = MagicMock()
        manager.ensure_project.return_value = Path("C:/synthetic/workspace")
        report = {
            "status": "needs_revision",
            "findings": [
                {
                    "severity": "error",
                    "category": "gameplay",
                    "message": "Ranged enemy behavior is missing",
                    "evidence": [
                        "game/unity_project/Assets/GameTemplate/Runtime/TowerDefense/Enemy.cs"
                    ],
                }
            ],
            "limitations": [],
        }
        evidence = {
            "game_logic_draft": {"status": "generated"},
            "parsed_request": {"condition": "Defend the base"},
        }
        harness = MagicMock()
        harness.repair_quality_findings.side_effect = [
            RuntimeError("error CS0103: helper type was not found"),
            SimpleNamespace(status="passed", checks=[], issues=[], unity_log="passed"),
        ]
        with (
            patch.dict(
                os.environ,
                {"MAINFLOW_GAME_BUILDER": "codex_cli", "MAINFLOW_GAME_QUALITY_REPAIRS": "2"},
            ),
            patch("game_pipeline.codex_cli.CodexHarnessSettings.from_environment"),
            patch("game_pipeline.codex_cli.CodexGameHarness", return_value=harness),
            patch(
                "mainflow.nodes.game_quality_validator.run_codex_quality_review",
                return_value={"status": "passed", "findings": []},
            ),
        ):
            result = _repair_and_review_quality("test-project", manager, evidence, report)

        self.assertEqual(result["status"], "passed")
        self.assertEqual(harness.repair_quality_findings.call_count, 2)
        second_findings = harness.repair_quality_findings.call_args_list[1].kwargs["findings"]
        self.assertTrue(
            any("previous quality patch" in finding["message"] for finding in second_findings)
        )

    def test_quality_repair_stops_when_same_finding_makes_no_source_progress(self) -> None:
        manager = MagicMock()
        manager.ensure_project.return_value = Path("C:/synthetic/workspace")
        report = {
            "status": "needs_revision",
            "findings": [
                {
                    "severity": "error",
                    "category": "progression",
                    "message": "The final collectible is unreachable",
                    "evidence": ["game/design/level_plan.json"],
                }
            ],
            "limitations": [],
        }
        evidence = {
            "game_logic_draft": {"status": "generated"},
            "parsed_request": {"condition": "Collect every shard"},
        }
        harness = MagicMock()
        harness.repair_quality_findings.return_value = SimpleNamespace(
            status="passed", checks=[], issues=[], unity_log="passed"
        )
        with (
            patch.dict(
                os.environ,
                {"MAINFLOW_GAME_BUILDER": "codex_cli", "MAINFLOW_GAME_QUALITY_REPAIRS": "10"},
            ),
            patch("game_pipeline.codex_cli.CodexHarnessSettings.from_environment"),
            patch("game_pipeline.codex_cli.CodexGameHarness", return_value=harness),
            patch(
                "mainflow.nodes.game_quality_validator.run_codex_quality_review",
                return_value=report,
            ),
        ):
            result = _repair_and_review_quality("test-project", manager, evidence, report)

        self.assertEqual(result["status"], "needs_revision")
        self.assertEqual(harness.repair_quality_findings.call_count, 3)
        self.assertTrue(
            any(
                call.args[2] == "quality_repair/stalled.json"
                for call in manager.write_json.call_args_list
            )
        )

    def test_quality_repair_stops_on_host_os_error(self) -> None:
        manager = MagicMock()
        manager.ensure_project.return_value = Path("C:/synthetic/workspace")
        report = {
            "status": "needs_revision",
            "findings": [
                {
                    "severity": "error",
                    "category": "gameplay",
                    "message": "Player health is incorrect",
                    "evidence": ["Assets/GameTemplate/Runtime/Player.cs"],
                }
            ],
        }
        harness = MagicMock()
        harness.repair_quality_findings.side_effect = OSError(22, "Invalid argument")
        with (
            patch.dict(
                os.environ,
                {"MAINFLOW_GAME_BUILDER": "codex_cli", "MAINFLOW_GAME_QUALITY_REPAIRS": "8"},
            ),
            patch("game_pipeline.codex_cli.CodexHarnessSettings.from_environment"),
            patch("game_pipeline.codex_cli.CodexGameHarness", return_value=harness),
        ):
            with self.assertRaises(OSError):
                _repair_and_review_quality(
                    "test-project",
                    manager,
                    {"game_logic_draft": {}, "parsed_request": {"condition": "Platformer"}},
                    report,
                )

        harness.repair_quality_findings.assert_called_once()
        self.assertTrue(
            any(
                call.args[2] == "quality_repair/repair_error_01.json"
                for call in manager.write_json.call_args_list
            )
        )

    def test_quality_validator_exposes_unexpected_error_in_log_and_result(self) -> None:
        manager = MagicMock()
        manager.read_json.return_value = {"status": "passed"}
        manager.ensure_project.return_value = Path("C:/synthetic/workspace")
        project_id = "20261115_10"
        keys = (
            "parsed_request",
            "logic_analysis",
            "game_logic_draft",
            "game_validation_result",
            "image_validation_result",
            "sound_validation_result",
            "integrated_game",
            "final_validation_result",
        )
        state = {"project_id": project_id, **{key: {"project_id": project_id} for key in keys}}
        with (
            patch.dict(os.environ, {"MAINFLOW_GAME_BUILDER": "codex_cli"}),
            patch("mainflow.nodes.game_quality_validator.ArtifactManager", return_value=manager),
            patch(
                "mainflow.nodes.game_quality_validator.run_codex_quality_review",
                side_effect=OSError(22, "Invalid argument"),
            ),
            patch("mainflow.nodes.game_quality_validator.log") as workflow_log,
        ):
            game_quality_validator_node(state)  # type: ignore[arg-type]

        self.assertTrue(any("OSError" in call.args[0] for call in workflow_log.call_args_list))
        error_record = next(
            call
            for call in manager.write_json.call_args_list
            if call.args[2] == "game_quality_validator_error.json"
        )
        self.assertIn("Traceback", error_record.args[3]["traceback"])
        final_report = manager.write_json.call_args_list[-1].args[3]
        self.assertEqual(final_report["status"], "failed")
        self.assertIn("OSError", final_report["summary"])

    def test_independent_validator_uses_project_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory) / "workspace"
            with patch.dict(os.environ, {"MAINFLOW_WORKSPACE": str(workspace)}):
                artifact_manager = ArtifactManager()
                project_id = artifact_manager.create_project()
                artifact_manager.write_project_text(
                    project_id,
                    "game/unity_project/Design.json",
                    "{}",
                )
                artifact_manager.write_project_text(
                    project_id,
                    "game/project_context_index.json",
                    '{"index_version":"1.0.0"}',
                )
                provider = QualityProvider(project_id)
                validator = GameQualityValidatorAI(
                    MCPManager(
                        "game_quality_validator",
                        server_target=mcp,
                        project_id=project_id,
                    ),
                    provider,
                )
                report = validator.evaluate(
                    project_id,
                    {
                        "parsed_request": {"condition": "reach the goal"},
                        "final_validation_result": {"status": "passed"},
                    },
                )

        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["score"], 88)
        self.assertEqual(report["provider"], "fake")
        self.assertTrue(provider.closed)

    def test_node_does_not_ask_ai_to_override_hard_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory) / "workspace"
            with patch.dict(os.environ, {"MAINFLOW_WORKSPACE": str(workspace)}):
                manager = ArtifactManager()
                project_id = manager.create_project()
                state = {"project_id": project_id}
                for key in (
                    "parsed_request",
                    "logic_analysis",
                    "game_logic_draft",
                    "game_validation_result",
                    "image_validation_result",
                    "sound_validation_result",
                    "integrated_game",
                    "final_validation_result",
                ):
                    status = "failed" if key == "final_validation_result" else "passed"
                    state[key] = manager.write_json(
                        project_id,
                        "validation",
                        f"{key}.json",
                        {"status": status},
                        producer="test",
                    )
                with patch(
                    "mainflow.nodes.game_quality_validator."
                    "create_game_quality_validator_from_environment",
                    MagicMock(side_effect=AssertionError("AI must not run")),
                ):
                    output = game_quality_validator_node(state)  # type: ignore[arg-type]
                report = manager.read_json(output["game_validator_ai_result"])

        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["provider"], "none")
        self.assertIn("final_validation_result", report["findings"][0]["evidence"])


if __name__ == "__main__":
    unittest.main()

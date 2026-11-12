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
                    "evidence": ["Assets/GameTemplate/Runtime/TowerDefense/CannonTower.cs:42"],
                }
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

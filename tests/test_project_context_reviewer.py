from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from game_pipeline.project_context_reviewer import ProjectContextReviewer
from mainflow.ArtifactManager import ArtifactManager
from MCP.llm_types import (
    LLMConversationMessage,
    LLMProviderResponse,
    LLMToolCall,
)
from MCP.manager import MCPManager, MCPToolDefinition
from MCP.server import mcp


class ReviewingProvider:
    name = "fake"
    model = "fake-reviewer"

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
        names = {tool["name"] for tool in tools}
        assert names == {"list_project_files", "read_project_text", "search_project_text"}
        if self.calls == 1:
            assert require_tool
            return LLMProviderResponse(
                text="",
                tool_calls=(
                    LLMToolCall(
                        call_id="list-1",
                        name="list_project_files",
                        arguments={
                            "project_id": self.project_id,
                            "relative_directory": "game/unity_project",
                        },
                    ),
                ),
            )
        if self.calls == 2:
            return LLMProviderResponse(
                text="",
                tool_calls=(
                    LLMToolCall(
                        call_id="search-1",
                        name="search_project_text",
                        arguments={
                            "project_id": self.project_id,
                            "relative_directory": "game/unity_project",
                            "query": "GeneratedFeatureBindingContext",
                            "glob_pattern": "*.cs",
                        },
                    ),
                ),
            )
        if self.calls == 3:
            return LLMProviderResponse(
                text="",
                tool_calls=(
                    LLMToolCall(
                        call_id="read-1",
                        name="read_project_text",
                        arguments={
                            "project_id": self.project_id,
                            "relative_path": (
                                "game/unity_project/Assets/GameTemplate/Generated/Scripts/"
                                "TimeRewindModule.cs"
                            ),
                        },
                    ),
                ),
            )
        return LLMProviderResponse(
            text=json.dumps(
                {
                    "approved": True,
                    "summary": "The generated binding API exists and matches its use.",
                    "inspected_files": [
                        "game/unity_project/Assets/GameTemplate/Generated/Scripts/"
                        "TimeRewindModule.cs"
                    ],
                    "issues": [],
                }
            )
        )

    async def aclose(self) -> None:
        self.closed = True


class ProjectContextReviewerTest(unittest.TestCase):
    def test_review_uses_read_only_mcp_tools_and_returns_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory) / "workspace"
            with patch.dict(os.environ, {"MAINFLOW_WORKSPACE": str(workspace)}):
                manager = ArtifactManager()
                project_id = manager.create_project()
                relative_path = (
                    "game/unity_project/Assets/GameTemplate/Generated/Scripts/TimeRewindModule.cs"
                )
                manager.write_project_text(
                    project_id,
                    relative_path,
                    "public class TimeRewindModule : GeneratedFeatureBindingContext {}\n",
                )
                provider = ReviewingProvider(project_id)
                reviewer = ProjectContextReviewer(
                    MCPManager(
                        "project_context_review",
                        server_target=mcp,
                        project_id=project_id,
                    ),
                    provider,
                )
                report = reviewer.review(
                    project_id,
                    {
                        "generated_modules": [
                            {
                                "module_id": "time_rewind",
                                "class_name": "TimeRewindModule",
                                "feature_description": "rewind player state",
                            }
                        ]
                    },
                )

        self.assertTrue(report["approved"])
        self.assertEqual(report["provider"], "fake")
        self.assertEqual(report["turns"], 4)
        self.assertIn("search_project_text", report["tool_calls"])
        self.assertTrue(provider.closed)


if __name__ == "__main__":
    unittest.main()

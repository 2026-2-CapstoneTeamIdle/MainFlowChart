from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mainflow.ArtifactManager import ArtifactManager
from MCP.llm_config import LLMSettings
from MCP.llm_runner import MCPToolLLMRunner
from MCP.llm_types import (
    LLMConversationMessage,
    LLMProviderResponse,
    LLMToolCall,
)
from MCP.manager import MCPManager, MCPToolDefinition
from MCP.server import mcp


class FileReadingProvider:
    name = "fake"
    model = "fake-tool-model"

    def __init__(self, project_id: str, relative_path: str) -> None:
        self.project_id = project_id
        self.relative_path = relative_path
        self.requests: list[list[LLMConversationMessage]] = []

    async def complete(
        self,
        messages: list[LLMConversationMessage],
        tools: list[MCPToolDefinition],
        *,
        system_prompt: str | None,
        temperature: float,
        require_tool: bool,
    ) -> LLMProviderResponse:
        self.requests.append(list(messages))
        if len(self.requests) == 1:
            self._assert_tool_is_visible(tools)
            return LLMProviderResponse(
                text="",
                tool_calls=(
                    LLMToolCall(
                        call_id="read-1",
                        name="read_project_text",
                        arguments={
                            "project_id": self.project_id,
                            "relative_path": self.relative_path,
                        },
                    ),
                ),
            )

        tool_message = messages[-1]
        assert tool_message.tool_result is not None
        return LLMProviderResponse(text=tool_message.tool_result["content"])

    @staticmethod
    def _assert_tool_is_visible(tools: list[MCPToolDefinition]) -> None:
        names = {tool["name"] for tool in tools}
        assert "read_project_text" in names

    async def aclose(self) -> None:
        return None


class ForbiddenWritingProvider:
    name = "fake"
    model = "fake-tool-model"

    async def complete(
        self,
        messages: list[LLMConversationMessage],
        tools: list[MCPToolDefinition],
        *,
        system_prompt: str | None,
        temperature: float,
        require_tool: bool,
    ) -> LLMProviderResponse:
        return LLMProviderResponse(
            text="",
            tool_calls=(
                LLMToolCall(
                    call_id="write-1",
                    name="write_project_text",
                    arguments={
                        "project_id": "20261014_01",
                        "relative_path": "data/forbidden.txt",
                        "content": "forbidden",
                    },
                ),
            ),
        )

    async def aclose(self) -> None:
        return None


class LLMRunnerTest(unittest.IsolatedAsyncioTestCase):
    async def test_runner_executes_mcp_call_and_returns_normalized_result(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory) / "workspace"
            with patch.dict(os.environ, {"MAINFLOW_WORKSPACE": str(workspace)}):
                artifact_manager = ArtifactManager()
                project_id = artifact_manager.create_project()
                relative_path = "data/runner_input.txt"
                artifact_manager.write_project_text(project_id, relative_path, "runner-ok")

                provider = FileReadingProvider(project_id, relative_path)
                runner = MCPToolLLMRunner(
                    MCPManager(
                        "analysis",
                        server_target=mcp,
                        project_id=project_id,
                    ),
                    provider,
                )
                result = await runner.run("파일을 읽어 주세요.", require_tool=True)

        self.assertEqual(result.text, "runner-ok")
        self.assertEqual(result.provider, "fake")
        self.assertEqual(result.model, "fake-tool-model")
        self.assertEqual(result.turns, 2)
        self.assertEqual(len(result.tool_calls), 1)
        self.assertEqual(result.tool_calls[0].name, "read_project_text")
        self.assertEqual(len(provider.requests), 2)

    async def test_runner_keeps_node_tool_permissions(self) -> None:
        runner = MCPToolLLMRunner(
            MCPManager("user_input", server_target=mcp),
            ForbiddenWritingProvider(),
        )
        with self.assertRaises(PermissionError):
            await runner.run("허용되지 않은 쓰기를 시도합니다.")

    def test_settings_support_node_specific_gemini_openai_and_local(self) -> None:
        environment = {
            "LLM_PROVIDER": "gemini",
            "GEMINI_API_KEY": "gemini-key",
            "LLM_ANALYSIS_PROVIDER": "openai",
            "LLM_ANALYSIS_MODEL": "analysis-model",
            "OPENAI_API_KEY": "openai-key",
            "LOCAL_LLM_BASE_URL": "http://local-model:11434/v1",
            "LOCAL_LLM_MODEL": "local-model",
        }
        with patch.dict(os.environ, environment, clear=True):
            gemini = LLMSettings.from_environment(node_name="parse_input")
            openai = LLMSettings.from_environment(node_name="analysis")
            local = LLMSettings.from_environment(
                node_name="logic_analysis",
                provider="LocalSLM",
            )

        self.assertEqual(gemini.provider, "gemini")
        self.assertEqual(gemini.api_key, "gemini-key")
        self.assertEqual(openai.provider, "openai")
        self.assertEqual(openai.model, "analysis-model")
        self.assertEqual(openai.api_key, "openai-key")
        self.assertEqual(local.provider, "local")
        self.assertEqual(local.model, "local-model")
        self.assertEqual(local.base_url, "http://local-model:11434/v1")


if __name__ == "__main__":
    unittest.main()

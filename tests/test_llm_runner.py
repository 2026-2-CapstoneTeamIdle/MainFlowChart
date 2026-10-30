from __future__ import annotations

import os
import tempfile
import unittest
from base64 import b64encode
from pathlib import Path
from unittest.mock import AsyncMock, patch

from LocalAI.profiles import AI_MODEL_PROFILES, resolve_ai_settings
from mainflow.ArtifactManager import ArtifactManager
from MCP.image_provider import GeneratedImageData, LocalImageGenerationProvider
from MCP.llm_config import LLMSettings
from MCP.llm_runner import MCPToolLLMRunner, run_node_llm
from MCP.llm_types import (
    ImageGenerationOptions,
    ImageRunResult,
    LLMConversationMessage,
    LLMProviderResponse,
    LLMToolCall,
)
from MCP.manager import MCPManager, MCPToolDefinition
from MCP.node_context import bind_mcp_tools
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

    def test_named_local_ai_profile_resolves_model_and_endpoint(self) -> None:
        environment = {
            "LOCAL_LLM_BASE_URL": "http://Local-AIModel:8080/v1",
            "LOCAL_LLM_API_KEY": "local-secret",
            "LLM_TIMEOUT_SECONDS": "300",
        }
        with patch.dict(os.environ, environment, clear=True):
            settings = resolve_ai_settings("Gemma4-E4B", "analysis")

        self.assertIn("gemma4_e4b", AI_MODEL_PROFILES)
        self.assertEqual(settings.provider, "local")
        self.assertEqual(settings.model, "gemma4-e4b")
        self.assertEqual(settings.base_url, "http://Local-AIModel:8080/v1")
        self.assertEqual(settings.api_key, "local-secret")
        self.assertEqual(settings.timeout_seconds, 300)

    def test_unknown_local_ai_profile_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            resolve_ai_settings("not-registered", "analysis")

    def test_sd_turbo_profile_is_image_only(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = resolve_ai_settings("sd-turbo", "generate_image", capability="image")

        self.assertEqual(settings.provider, "local")
        self.assertEqual(settings.model, "sd-turbo")
        self.assertEqual(settings.base_url, "http://127.0.0.1:8080/v1")
        with self.assertRaises(ValueError):
            resolve_ai_settings("sd-turbo", "analysis")

    async def test_image_output_is_saved_as_project_artifact(self) -> None:
        png = b"\x89PNG\r\n\x1a\nnode-image"
        generated = GeneratedImageData(png, "image/png", ".png")

        async def image_node(state: dict[str, str]) -> ImageRunResult:
            result = await run_node_llm(
                "pixel art forest platformer",
                ai="sd_turbo",
                output="image",
                image_options=ImageGenerationOptions(filename_prefix="target_scene"),
            )
            assert isinstance(result, ImageRunResult)
            return result

        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory) / "workspace"
            with patch.dict(os.environ, {"MAINFLOW_WORKSPACE": str(workspace)}):
                artifact_manager = ArtifactManager()
                project_id = artifact_manager.create_project()
                bound_node = bind_mcp_tools("generate_image", image_node)
                with patch.object(
                    LocalImageGenerationProvider,
                    "generate",
                    AsyncMock(return_value=(generated,)),
                ):
                    result = await bound_node({"project_id": project_id})

                self.assertEqual(result.provider, "local")
                self.assertEqual(result.model, "sd-turbo")
                self.assertEqual(len(result.artifacts), 1)
                self.assertEqual(
                    artifact_manager.read_bytes(result.artifacts[0]),
                    png,
                )
                self.assertTrue(
                    result.artifacts[0]["relative_path"].startswith(
                        "generated/images/target_scene_01_"
                    )
                )

    async def test_local_image_provider_accepts_base64_response(self) -> None:
        png = b"\x89PNG\r\n\x1a\nprovider-image"
        settings = LLMSettings(
            provider="local",
            model="sd-turbo",
            api_key=None,
            base_url="http://127.0.0.1:8080/v1",
            timeout_seconds=30,
        )
        provider = LocalImageGenerationProvider(settings)
        with patch.object(
            provider,
            "_post_json",
            return_value={"data": [{"b64_json": b64encode(png).decode("ascii")}]},
        ) as request:
            images = await provider.generate(
                "pixel art tower",
                ImageGenerationOptions(size="512x512", steps=2),
            )

        self.assertEqual(images[0].content, png)
        payload = request.call_args.args[0]
        self.assertEqual(payload["model"], "sd-turbo")
        self.assertEqual(payload["step"], 2)
        self.assertEqual(payload["response_format"], "b64_json")


if __name__ == "__main__":
    unittest.main()

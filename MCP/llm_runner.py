"""Common LLM tool loop used directly inside workflow nodes."""

from __future__ import annotations

import os
import uuid
from typing import Any

from mainflow.ArtifactManager import ArtifactManager
from MCP.image_provider import LocalImageGenerationProvider
from MCP.llm_config import LLMSettings
from MCP.llm_providers import create_llm_provider
from MCP.llm_types import (
    ImageGenerationOptions,
    ImageRunResult,
    LLMConversationMessage,
    LLMProvider,
    LLMRunResult,
    LLMToolExecution,
    NodeOutputMode,
    NodeRunOutput,
)
from MCP.manager import MCPManager, MCPToolCallResult
from MCP.node_context import get_current_mcp_manager


def _tool_payload(result: MCPToolCallResult) -> dict[str, Any]:
    if result["structured_content"] is not None:
        return result["structured_content"]
    return {
        "is_error": result["is_error"],
        "content": result["content"],
    }


class MCPToolLLMRunner:
    """Run one provider while automatically executing its allowed MCP calls."""

    def __init__(self, manager: MCPManager, provider: LLMProvider) -> None:
        self._manager = manager
        self._provider = provider

    async def run(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        temperature: float = 0.0,
        max_tool_rounds: int = 4,
        require_tool: bool = False,
    ) -> LLMRunResult:
        """Return final text after zero or more permission-checked MCP calls."""

        if not prompt.strip():
            raise ValueError("prompt must not be empty")
        if max_tool_rounds < 0:
            raise ValueError("max_tool_rounds must be zero or greater")

        messages = [LLMConversationMessage(role="user", content=prompt)]
        executions: list[LLMToolExecution] = []
        turns = 0

        async with self._manager.connect() as mcp_session:
            tools = await mcp_session.tool_definitions()
            while True:
                turns += 1
                response = await self._provider.complete(
                    messages,
                    tools,
                    system_prompt=system_prompt,
                    temperature=temperature,
                    require_tool=require_tool and turns == 1,
                )
                messages.append(
                    LLMConversationMessage(
                        role="assistant",
                        content=response.text,
                        tool_calls=response.tool_calls,
                    )
                )
                if not response.tool_calls:
                    return LLMRunResult(
                        text=response.text,
                        provider=self._provider.name,
                        model=self._provider.model,
                        turns=turns,
                        tool_calls=tuple(executions),
                    )
                if turns > max_tool_rounds:
                    raise RuntimeError(
                        f"LLM exceeded the maximum of {max_tool_rounds} tool-call rounds"
                    )

                for call in response.tool_calls:
                    tool_result = await mcp_session.call_tool(call.name, call.arguments)
                    payload = _tool_payload(tool_result)
                    executions.append(
                        LLMToolExecution(
                            call_id=call.call_id,
                            name=call.name,
                            arguments=call.arguments,
                            result=payload,
                        )
                    )
                    messages.append(
                        LLMConversationMessage(
                            role="tool",
                            tool_call_id=call.call_id,
                            tool_name=call.name,
                            tool_result=payload,
                        )
                    )


async def run_node_llm(
    prompt: str,
    *,
    system_prompt: str | None = None,
    ai: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    temperature: float = 0.0,
    max_tool_rounds: int = 4,
    require_tool: bool = False,
    output: NodeOutputMode = "text",
    image_options: ImageGenerationOptions | None = None,
) -> NodeRunOutput:
    """Run text/MCP generation or persist images from a local image model."""

    manager = get_current_mcp_manager()
    if output == "image":
        if require_tool:
            raise ValueError("Image generation cannot require an MCP tool call")
        if manager.project_id is None:
            raise RuntimeError("Image generation requires a project_id-bound workflow node")
        if not prompt.strip():
            raise ValueError("prompt must not be empty")

        if ai is not None:
            if provider is not None or model is not None:
                raise ValueError("ai cannot be combined with provider or model")
            from LocalAI.profiles import resolve_ai_settings

            settings = resolve_ai_settings(ai, manager.node_name, capability="image")
        else:
            if provider is not None and provider.strip().lower() not in {
                "local",
                "localslm",
                "local_slm",
            }:
                raise ValueError("Image generation currently supports only the local provider")
            image_model = model or os.environ.get("LOCAL_IMAGE_MODEL", "sd-turbo")
            settings = LLMSettings.from_environment(
                node_name=manager.node_name,
                provider="local",
                model=image_model,
            )
            image_base_url = os.environ.get("LOCAL_IMAGE_BASE_URL")
            if image_base_url:
                settings = LLMSettings(
                    provider=settings.provider,
                    model=settings.model,
                    api_key=settings.api_key,
                    base_url=image_base_url.strip(),
                    timeout_seconds=settings.timeout_seconds,
                )

        options = image_options or ImageGenerationOptions()
        effective_prompt = prompt.strip()
        if system_prompt and system_prompt.strip():
            effective_prompt = f"{system_prompt.strip()}\n\n{effective_prompt}"
        image_provider = LocalImageGenerationProvider(settings)
        generated_images = await image_provider.generate(effective_prompt, options)
        artifact_manager = ArtifactManager()
        artifacts = []
        for index, generated_image in enumerate(generated_images, start=1):
            unique_suffix = uuid.uuid4().hex[:8]
            filename = (
                f"{options.filename_prefix}_{index:02d}_{unique_suffix}{generated_image.extension}"
            )
            artifacts.append(
                artifact_manager.write_bytes(
                    manager.project_id,
                    "image",
                    filename,
                    generated_image.content,
                    producer=f"{manager.node_name}:run_node_llm",
                    media_type=generated_image.media_type,
                )
            )
        return ImageRunResult(
            artifacts=tuple(artifacts),
            provider=image_provider.name,
            model=image_provider.model,
            prompt=effective_prompt,
            size=options.size,
        )
    if output != "text":
        raise ValueError("output must be either 'text' or 'image'")
    if image_options is not None:
        raise ValueError("image_options can only be used with output='image'")

    if ai is not None:
        if provider is not None or model is not None:
            raise ValueError("ai cannot be combined with provider or model")
        from LocalAI.profiles import resolve_ai_settings

        settings = resolve_ai_settings(ai, manager.node_name)
    else:
        settings = LLMSettings.from_environment(
            node_name=manager.node_name,
            provider=provider,
            model=model,
        )
    llm_provider = create_llm_provider(settings)
    runner = MCPToolLLMRunner(manager, llm_provider)
    try:
        return await runner.run(
            prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tool_rounds=max_tool_rounds,
            require_tool=require_tool,
        )
    finally:
        await llm_provider.aclose()


async def run_llm(
    prompt: str,
    *,
    system_prompt: str | None = None,
    ai: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    temperature: float = 0.0,
    max_tool_rounds: int = 4,
    require_tool: bool = False,
    output: NodeOutputMode = "text",
    image_options: ImageGenerationOptions | None = None,
) -> NodeRunOutput:
    """Convenience name for invoking an LLM from a bound workflow node."""

    return await run_node_llm(
        prompt,
        system_prompt=system_prompt,
        ai=ai,
        provider=provider,
        model=model,
        temperature=temperature,
        max_tool_rounds=max_tool_rounds,
        require_tool=require_tool,
        output=output,
        image_options=image_options,
    )

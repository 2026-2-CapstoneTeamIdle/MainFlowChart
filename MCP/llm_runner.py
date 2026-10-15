"""Common LLM tool loop used directly inside workflow nodes."""

from __future__ import annotations

from typing import Any

from MCP.llm_config import LLMSettings
from MCP.llm_providers import create_llm_provider
from MCP.llm_types import (
    LLMConversationMessage,
    LLMProvider,
    LLMRunResult,
    LLMToolExecution,
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
) -> LLMRunResult:
    """Use the current node's MCP policy with a selected LLM provider."""

    manager = get_current_mcp_manager()
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
) -> LLMRunResult:
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
    )

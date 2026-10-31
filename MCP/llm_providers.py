"""Gemini and OpenAI-compatible adapters for the common LLM runner."""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
import uuid
from typing import Any

from MCP.llm_config import LLMSettings
from MCP.llm_types import (
    LLMConversationMessage,
    LLMProvider,
    LLMProviderResponse,
    LLMToolCall,
)
from MCP.manager import MCPToolDefinition


class LLMProviderError(RuntimeError):
    """Raised when a provider response cannot be used by the common runner."""


class GeminiProvider:
    """Google Gen AI adapter using native Gemini function calling."""

    name = "gemini"

    def __init__(self, settings: LLMSettings) -> None:
        if not settings.api_key:
            raise RuntimeError("GEMINI_API_KEY is not set")

        from google import genai
        from google.genai import types

        self.model = settings.model
        self._types = types
        self._client = genai.Client(api_key=settings.api_key)

    def _contents(self, messages: list[LLMConversationMessage]) -> list[Any]:
        types = self._types
        contents: list[Any] = []
        for message in messages:
            if message.role == "user":
                contents.append(
                    types.Content(
                        role="user",
                        parts=[types.Part.from_text(text=message.content)],
                    )
                )
                continue
            if message.role == "assistant":
                parts = []
                if message.content:
                    parts.append(types.Part.from_text(text=message.content))
                parts.extend(
                    types.Part.from_function_call(
                        name=call.name,
                        args=call.arguments,
                    )
                    for call in message.tool_calls
                )
                contents.append(types.Content(role="model", parts=parts))
                continue
            if message.role == "tool":
                if message.tool_name is None or message.tool_result is None:
                    raise ValueError("Tool messages require a name and result")
                contents.append(
                    types.Content(
                        role="tool",
                        parts=[
                            types.Part.from_function_response(
                                name=message.tool_name,
                                response=message.tool_result,
                            )
                        ],
                    )
                )
                continue
            raise ValueError(f"Unsupported conversation role: {message.role}")
        return contents

    async def complete(
        self,
        messages: list[LLMConversationMessage],
        tools: list[MCPToolDefinition],
        *,
        system_prompt: str | None,
        temperature: float,
        require_tool: bool,
        max_tokens: int | None = None,
    ) -> LLMProviderResponse:
        types = self._types
        gemini_tools = []
        if tools:
            gemini_tools.append(
                types.Tool(
                    function_declarations=[
                        types.FunctionDeclaration(
                            name=tool["name"],
                            description=tool["description"],
                            parameters_json_schema=tool["input_schema"],
                        )
                        for tool in tools
                    ]
                )
            )

        tool_config = None
        if tools:
            mode = "ANY" if require_tool else "AUTO"
            tool_config = types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(
                    mode=mode,
                    allowed_function_names=(
                        [tool["name"] for tool in tools] if require_tool else None
                    ),
                )
            )

        response = await self._client.aio.models.generate_content(
            model=self.model,
            contents=self._contents(messages),
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=temperature,
                max_output_tokens=max_tokens,
                tools=gemini_tools or None,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                tool_config=tool_config,
            ),
        )
        if not response.candidates or response.candidates[0].content is None:
            raise LLMProviderError("Gemini returned no candidate content")

        calls = tuple(
            LLMToolCall(
                call_id=getattr(call, "id", None) or uuid.uuid4().hex,
                name=call.name,
                arguments=dict(call.args or {}),
            )
            for call in response.function_calls or []
            if call.name
        )
        return LLMProviderResponse(text=(response.text or "").strip(), tool_calls=calls)

    async def aclose(self) -> None:
        await self._client.aio.aclose()


class OpenAICompatibleProvider:
    """Chat Completions adapter shared by OpenAI and local OpenAI-compatible SLMs."""

    def __init__(self, settings: LLMSettings) -> None:
        if settings.provider == "openai" and not settings.api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        if settings.base_url is None:
            raise ValueError("An OpenAI-compatible provider requires a base URL")

        self.name = settings.provider
        self.model = settings.model
        self._api_key = settings.api_key
        self._base_url = settings.base_url.rstrip("/")
        self._timeout_seconds = settings.timeout_seconds

    @staticmethod
    def _messages(
        messages: list[LLMConversationMessage],
        system_prompt: str | None,
    ) -> list[dict[str, Any]]:
        payload: list[dict[str, Any]] = []
        if system_prompt:
            payload.append({"role": "system", "content": system_prompt})
        for message in messages:
            if message.role in {"user", "assistant"}:
                item: dict[str, Any] = {
                    "role": message.role,
                    "content": message.content or None,
                }
                if message.tool_calls:
                    item["tool_calls"] = [
                        {
                            "id": call.call_id,
                            "type": "function",
                            "function": {
                                "name": call.name,
                                "arguments": json.dumps(
                                    call.arguments,
                                    ensure_ascii=False,
                                ),
                            },
                        }
                        for call in message.tool_calls
                    ]
                payload.append(item)
                continue
            if message.role == "tool":
                if message.tool_call_id is None or message.tool_result is None:
                    raise ValueError("Tool messages require a call ID and result")
                payload.append(
                    {
                        "role": "tool",
                        "tool_call_id": message.tool_call_id,
                        "content": json.dumps(message.tool_result, ensure_ascii=False),
                    }
                )
                continue
            raise ValueError(f"Unsupported conversation role: {message.role}")
        return payload

    def _post_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        request = urllib.request.Request(
            f"{self._base_url}/chat/completions",
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            raise LLMProviderError(
                f"{self.name} request failed with HTTP status {error.code}"
            ) from None
        except urllib.error.URLError as error:
            raise LLMProviderError(f"Could not connect to {self.name} provider") from error

    async def complete(
        self,
        messages: list[LLMConversationMessage],
        tools: list[MCPToolDefinition],
        *,
        system_prompt: str | None,
        temperature: float,
        require_tool: bool,
        max_tokens: int | None = None,
    ) -> LLMProviderResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": self._messages(messages, system_prompt),
            "temperature": temperature,
        }
        if max_tokens is not None:
            if max_tokens < 1:
                raise ValueError("max_tokens must be positive")
            payload["max_tokens"] = max_tokens
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool["description"],
                        "parameters": tool["input_schema"],
                    },
                }
                for tool in tools
            ]
            payload["tool_choice"] = "required" if require_tool else "auto"

        response = await asyncio.to_thread(self._post_json, payload)
        try:
            message = response["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as error:
            raise LLMProviderError(f"{self.name} returned an invalid response") from error

        tool_calls: list[LLMToolCall] = []
        for item in message.get("tool_calls") or []:
            function = item.get("function") or {}
            name = function.get("name")
            if not name:
                raise LLMProviderError(f"{self.name} returned a tool call without a name")
            raw_arguments = function.get("arguments") or "{}"
            try:
                arguments = (
                    raw_arguments if isinstance(raw_arguments, dict) else json.loads(raw_arguments)
                )
            except json.JSONDecodeError as error:
                raise LLMProviderError(
                    f"{self.name} returned invalid JSON tool arguments"
                ) from error
            if not isinstance(arguments, dict):
                raise LLMProviderError("Tool arguments must be a JSON object")
            tool_calls.append(
                LLMToolCall(
                    call_id=item.get("id") or uuid.uuid4().hex,
                    name=name,
                    arguments=arguments,
                )
            )

        content = message.get("content") or ""
        if not isinstance(content, str):
            raise LLMProviderError(f"{self.name} returned non-text content")
        return LLMProviderResponse(text=content.strip(), tool_calls=tuple(tool_calls))

    async def aclose(self) -> None:
        return None


def create_llm_provider(settings: LLMSettings) -> LLMProvider:
    """Create the adapter selected by resolved settings."""

    if settings.provider == "gemini":
        return GeminiProvider(settings)
    if settings.provider in {"openai", "local", "vastai"}:
        return OpenAICompatibleProvider(settings)
    raise ValueError(f"Unsupported LLM provider: {settings.provider}")

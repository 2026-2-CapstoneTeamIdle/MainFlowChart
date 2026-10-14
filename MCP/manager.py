"""MCP client facade that exposes only tools allowed for one workflow node."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, TypedDict

from mcp import Client
from MCP.config import MCPSettings
from MCP.policies import allowed_tools_for_node


class MCPToolDefinition(TypedDict):
    name: str
    description: str
    input_schema: dict[str, Any]


class MCPToolCallResult(TypedDict):
    is_error: bool
    structured_content: dict[str, Any] | None
    content: list[dict[str, Any]]


class MCPNodeSession:
    """Connected MCP session scoped to a single workflow node."""

    def __init__(self, node_name: str, client: Client) -> None:
        self.node_name = node_name
        self._client = client
        self._allowed_tools = allowed_tools_for_node(node_name)

    async def tool_definitions(self) -> list[MCPToolDefinition]:
        """Return generic definitions suitable for an LLM tool adapter."""

        definitions: list[MCPToolDefinition] = []
        cursor: str | None = None
        while True:
            page = await self._client.list_tools(cursor=cursor)
            for tool in page.tools:
                if tool.name in self._allowed_tools:
                    definitions.append(
                        {
                            "name": tool.name,
                            "description": tool.description or "",
                            "input_schema": tool.input_schema,
                        }
                    )
            cursor = page.next_cursor
            if cursor is None:
                break
        return definitions

    async def openai_tool_definitions(self) -> list[dict[str, Any]]:
        """Return OpenAI-compatible function definitions without calling an LLM."""

        return [
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool["input_schema"],
                },
            }
            for tool in await self.tool_definitions()
        ]

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> MCPToolCallResult:
        """Invoke an allowed tool and return JSON-serializable MCP output."""

        if name not in self._allowed_tools:
            raise PermissionError(f"Node {self.node_name} cannot call MCP tool: {name}")

        result = await self._client.call_tool(name, arguments)
        content = [block.model_dump(by_alias=True, mode="json") for block in result.content]
        structured = result.structured_content
        return {
            "is_error": result.is_error,
            "structured_content": structured,
            "content": content,
        }


class MCPManager:
    """Create node-scoped sessions against HTTP or an in-process test server."""

    def __init__(
        self,
        node_name: str,
        server_target: object | None = None,
    ) -> None:
        allowed_tools_for_node(node_name)
        self.node_name = node_name
        self.server_target = server_target or MCPSettings.from_environment().server_url

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[MCPNodeSession]:
        """Open one reusable connection for an LLM tool-call loop."""

        async with Client(self.server_target) as client:
            yield MCPNodeSession(self.node_name, client)

    async def tool_definitions(self) -> list[MCPToolDefinition]:
        async with self.connect() as session:
            return await session.tool_definitions()

    async def openai_tool_definitions(self) -> list[dict[str, Any]]:
        async with self.connect() as session:
            return await session.openai_tool_definitions()

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> MCPToolCallResult:
        if name not in allowed_tools_for_node(self.node_name):
            raise PermissionError(f"Node {self.node_name} cannot call MCP tool: {name}")
        async with self.connect() as session:
            return await session.call_tool(name, arguments)

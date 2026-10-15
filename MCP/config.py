"""Environment-backed MCP configuration shared by Docker and local runs."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _csv_environment(name: str, default: str) -> tuple[str, ...]:
    values = tuple(value.strip() for value in os.environ.get(name, default).split(","))
    return tuple(value for value in values if value)


@dataclass(frozen=True)
class MCPSettings:
    """Runtime settings without secrets or provider-specific LLM configuration."""

    server_url: str
    host: str
    port: int
    max_text_bytes: int
    max_list_entries: int
    allowed_hosts: tuple[str, ...]
    allowed_origins: tuple[str, ...]

    @classmethod
    def from_environment(cls) -> MCPSettings:
        port = int(os.environ.get("MCP_PORT", "8001"))
        max_text_bytes = int(os.environ.get("MCP_MAX_TEXT_BYTES", str(256 * 1024)))
        max_list_entries = int(os.environ.get("MCP_MAX_LIST_ENTRIES", "200"))
        if not 1 <= port <= 65535:
            raise ValueError("MCP_PORT must be between 1 and 65535")
        if max_text_bytes < 1:
            raise ValueError("MCP_MAX_TEXT_BYTES must be greater than zero")
        if max_list_entries < 1:
            raise ValueError("MCP_MAX_LIST_ENTRIES must be greater than zero")

        return cls(
            server_url=os.environ.get("MCP_SERVER_URL", f"http://127.0.0.1:{port}/mcp"),
            host=os.environ.get("MCP_HOST", "127.0.0.1"),
            port=port,
            max_text_bytes=max_text_bytes,
            max_list_entries=max_list_entries,
            allowed_hosts=_csv_environment(
                "MCP_ALLOWED_HOSTS",
                "127.0.0.1,127.0.0.1:*,localhost,localhost:*,mcp-server,mcp-server:*",
            ),
            allowed_origins=_csv_environment(
                "MCP_ALLOWED_ORIGINS",
                "http://127.0.0.1:*,http://localhost:*",
            ),
        )

    @property
    def health_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/health"

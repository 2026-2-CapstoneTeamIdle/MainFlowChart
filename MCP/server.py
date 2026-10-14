"""Docker-ready Streamable HTTP MCP server for project working files."""

from __future__ import annotations

import hashlib
from typing import Any

from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from mainflow.ArtifactManager import ArtifactManager
from MCP.config import MCPSettings
from mcp.server import MCPServer

mcp = MCPServer("mainflow-filesystem")


def _file_payload(project_id: str, relative_path: str, content: bytes) -> dict[str, Any]:
    return {
        "project_id": project_id,
        "relative_path": relative_path,
        "size_bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "content": content.decode("utf-8"),
    }


@mcp.tool()
def list_project_files(
    project_id: str,
    relative_directory: str = ".",
    recursive: bool = True,
) -> dict[str, Any]:
    """List files inside one managed project workspace directory."""

    try:
        settings = MCPSettings.from_environment()
        manager = ArtifactManager()
        paths = manager.list_project_files(
            project_id,
            relative_directory,
            recursive=recursive,
            limit=settings.max_list_entries + 1,
        )
        project_root = manager.ensure_project(project_id)
        truncated = len(paths) > settings.max_list_entries
        files = []
        for path in paths[: settings.max_list_entries]:
            absolute = manager.resolve_project_path(project_id, path)
            files.append(
                {
                    "relative_path": path.as_posix(),
                    "size_bytes": absolute.stat().st_size,
                }
            )
        return {
            "project_id": project_id,
            "relative_directory": relative_directory,
            "files": files,
            "limit": settings.max_list_entries,
            "truncated": truncated,
            "project_root": project_root.name,
        }
    except (OSError, TypeError, ValueError) as error:
        raise ToolError(str(error)) from error


@mcp.tool()
def read_project_text(project_id: str, relative_path: str) -> dict[str, Any]:
    """Read one UTF-8 text file from a managed project workspace."""

    try:
        settings = MCPSettings.from_environment()
        content = ArtifactManager().read_project_file(
            project_id,
            relative_path,
            max_bytes=settings.max_text_bytes,
        )
        try:
            return _file_payload(project_id, relative_path, content)
        except UnicodeDecodeError as error:
            raise ValueError(f"File is not UTF-8 text: {relative_path}") from error
    except (OSError, TypeError, ValueError) as error:
        raise ToolError(str(error)) from error


@mcp.tool()
def write_project_text(
    project_id: str,
    relative_path: str,
    content: str,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    """Create or revise UTF-8 text using SHA-256 optimistic locking."""

    try:
        settings = MCPSettings.from_environment()
        encoded = content.encode("utf-8")
        if len(encoded) > settings.max_text_bytes:
            raise ValueError(
                f"Content exceeds MCP_MAX_TEXT_BYTES ({settings.max_text_bytes}): {relative_path}"
            )
        manager = ArtifactManager()
        manager.write_project_text(
            project_id,
            relative_path,
            content,
            expected_sha256=expected_sha256,
        )
        return _file_payload(project_id, relative_path, encoded)
    except (OSError, TypeError, ValueError) as error:
        raise ToolError(str(error)) from error


@mcp.custom_route("/health", methods=["GET"])
async def health(_request: Request) -> Response:
    return JSONResponse({"status": "ok", "service": "mainflow-mcp"})


def main() -> None:
    settings = MCPSettings.from_environment()
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=list(settings.allowed_hosts),
        allowed_origins=list(settings.allowed_origins),
    )
    mcp.run(
        transport="streamable-http",
        host=settings.host,
        port=settings.port,
        json_response=True,
        stateless_http=True,
        transport_security=security,
    )


if __name__ == "__main__":
    main()

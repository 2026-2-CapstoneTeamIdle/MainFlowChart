from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mainflow.ArtifactManager import ArtifactManager
from mcp import Client
from MCP.manager import MCPManager
from MCP.node_context import bind_mcp_tools, get_current_mcp_manager
from MCP.server import mcp


class MCPServerTest(unittest.IsolatedAsyncioTestCase):
    async def test_file_tools_round_trip_and_revision_guard(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory) / "workspace"
            with patch.dict(os.environ, {"MAINFLOW_WORKSPACE": str(workspace)}):
                project_id = ArtifactManager().create_project()
                async with Client(mcp, raise_exceptions=True) as client:
                    created = await client.call_tool(
                        "write_project_text",
                        {
                            "project_id": project_id,
                            "relative_path": "game/working/design.txt",
                            "content": "first",
                        },
                    )
                    self.assertFalse(created.is_error)
                    first_hash = created.structured_content["sha256"]

                    revised = await client.call_tool(
                        "write_project_text",
                        {
                            "project_id": project_id,
                            "relative_path": "game/working/design.txt",
                            "content": "second",
                            "expected_sha256": first_hash,
                        },
                    )
                    self.assertFalse(revised.is_error)

                    read = await client.call_tool(
                        "read_project_text",
                        {
                            "project_id": project_id,
                            "relative_path": "game/working/design.txt",
                        },
                    )
                    self.assertEqual(read.structured_content["content"], "second")

                    listed = await client.call_tool(
                        "list_project_files",
                        {"project_id": project_id, "relative_directory": "game"},
                    )
                    paths = [item["relative_path"] for item in listed.structured_content["files"]]
                    self.assertIn("game/working/design.txt", paths)

                    stale = await client.call_tool(
                        "write_project_text",
                        {
                            "project_id": project_id,
                            "relative_path": "game/working/design.txt",
                            "content": "stale",
                            "expected_sha256": first_hash,
                        },
                    )
                    self.assertTrue(stale.is_error)

    async def test_node_manager_filters_and_guards_tools(self) -> None:
        manager = MCPManager("user_input", server_target=mcp)
        definitions = await manager.tool_definitions()
        names = {tool["name"] for tool in definitions}
        openai_definitions = await manager.openai_tool_definitions()
        openai_names = {tool["function"]["name"] for tool in openai_definitions}

        self.assertEqual(names, {"list_project_files", "read_project_text"})
        self.assertEqual(openai_names, names)
        with self.assertRaises(PermissionError):
            await manager.call_tool("write_project_text", {})

    async def test_node_manager_rejects_a_different_project_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory) / "workspace"
            with patch.dict(os.environ, {"MAINFLOW_WORKSPACE": str(workspace)}):
                artifact_manager = ArtifactManager()
                active_project_id = artifact_manager.create_project()
                other_project_id = artifact_manager.create_project()
                artifact_manager.write_project_text(
                    other_project_id,
                    "data/private.txt",
                    "other-project",
                )
                manager = MCPManager(
                    "analysis",
                    server_target=mcp,
                    project_id=active_project_id,
                )

                with self.assertRaises(PermissionError):
                    await manager.call_tool(
                        "read_project_text",
                        {
                            "project_id": other_project_id,
                            "relative_path": "data/private.txt",
                        },
                    )

    async def test_node_manager_requires_a_bound_project_id(self) -> None:
        manager = MCPManager("analysis", server_target=mcp)
        with self.assertRaises(RuntimeError):
            await manager.call_tool(
                "list_project_files",
                {"project_id": "20261014_01"},
            )

    def test_node_wrapper_injects_scoped_manager(self) -> None:
        def node(state: dict[str, str]) -> dict[str, str]:
            manager = get_current_mcp_manager()
            return {
                "node_name": manager.node_name,
                "bound_project_id": manager.project_id or "",
                **state,
            }

        bound = bind_mcp_tools("analysis", node)
        self.assertEqual(
            bound({"project_id": "20261014_01", "value": "ok"}),
            {
                "node_name": "analysis",
                "bound_project_id": "20261014_01",
                "project_id": "20261014_01",
                "value": "ok",
            },
        )
        with self.assertRaises(RuntimeError):
            get_current_mcp_manager()


if __name__ == "__main__":
    unittest.main()

"""List node-scoped MCP tools through the configured HTTP endpoint."""

from __future__ import annotations

import argparse
import asyncio
import json

from MCP.manager import MCPManager


async def check(node_name: str) -> list[str]:
    definitions = await MCPManager(node_name).tool_definitions()
    return [tool["name"] for tool in definitions]


def main() -> int:
    parser = argparse.ArgumentParser(description="Check MCP connectivity for one workflow node.")
    parser.add_argument("--node", default="analysis", help="Registered LangGraph node name")
    arguments = parser.parse_args()
    tools = asyncio.run(check(arguments.node))
    print(json.dumps({"node": arguments.node, "tools": tools}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

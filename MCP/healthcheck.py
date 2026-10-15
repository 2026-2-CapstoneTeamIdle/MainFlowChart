"""Container health probe for the MCP HTTP service."""

from __future__ import annotations

import json
import urllib.request

from MCP.config import MCPSettings


def main() -> int:
    settings = MCPSettings.from_environment()
    with urllib.request.urlopen(settings.health_url, timeout=2) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return 0 if response.status == 200 and payload.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())

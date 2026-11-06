"""Environment configuration for the Claude Code game-development harness."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from game_pipeline.codex_cli.config import _integer_environment


@dataclass(frozen=True)
class ClaudeCodeHarnessSettings:
    executable: Path
    model: str | None
    reasoning_effort: None
    invocation_timeout_seconds: int
    total_timeout_seconds: int
    max_repairs: int
    max_turns: int
    permission_mode: str

    @classmethod
    def from_environment(cls) -> ClaudeCodeHarnessSettings:
        configured = os.environ.get("MAINFLOW_CLAUDE_CLI_PATH", "").strip()
        discovered = configured or _discover_claude_executable()
        if not discovered:
            raise FileNotFoundError(
                "Claude Code CLI was not found. Install @anthropic-ai/claude-code and ensure "
                "'claude' is on PATH, or set MAINFLOW_CLAUDE_CLI_PATH."
            )
        timeout = _integer_environment("MAINFLOW_CLAUDE_TIMEOUT_SECONDS", 1800, 60, 7200)
        total_timeout = _integer_environment(
            "MAINFLOW_CLAUDE_TOTAL_TIMEOUT_SECONDS", 7200, timeout, 21600
        )
        max_repairs = _integer_environment("MAINFLOW_CLAUDE_MAX_REPAIRS", 6, 0, 10)
        max_turns = _integer_environment("MAINFLOW_CLAUDE_MAX_TURNS", 80, 1, 200)
        permission_mode = os.environ.get("MAINFLOW_CLAUDE_PERMISSION_MODE", "acceptEdits").strip()
        if permission_mode not in {"default", "acceptEdits", "plan", "dontAsk"}:
            raise ValueError("MAINFLOW_CLAUDE_PERMISSION_MODE has an unsupported value")
        model = os.environ.get("MAINFLOW_CLAUDE_MODEL", "sonnet").strip() or None
        return cls(
            Path(discovered).resolve(),
            model,
            None,
            timeout,
            total_timeout,
            max_repairs,
            max_turns,
            permission_mode,
        )


def _discover_claude_executable() -> str | None:
    for name in ("claude", "claude.cmd", "claude.exe"):
        discovered = shutil.which(name)
        if discovered:
            return discovered
    app_data = os.environ.get("APPDATA", "").strip()
    if app_data:
        npm_shim = Path(app_data) / "npm" / "claude.cmd"
        if npm_shim.is_file():
            return str(npm_shim)
    return None

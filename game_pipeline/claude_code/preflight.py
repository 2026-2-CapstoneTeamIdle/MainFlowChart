"""Read-only installation check for Claude Code CLI."""

from __future__ import annotations

import subprocess

from game_pipeline.claude_code.config import ClaudeCodeHarnessSettings
from game_pipeline.codex_cli.preflight import CodexPreflightResult


def run_claude_code_preflight(
    settings: ClaudeCodeHarnessSettings,
) -> CodexPreflightResult:
    try:
        result = subprocess.run(
            [str(settings.executable), "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(f"CLAUDE_VERSION_CHECK_FAILED: {error}") from error
    output = (result.stdout + "\n" + result.stderr).strip()
    if result.returncode != 0:
        raise RuntimeError(
            f"CLAUDE_VERSION_CHECK_FAILED: {output or f'exit code {result.returncode}'}"
        )
    # Claude Code has no stable, read-only login-status command. The first print-mode request
    # performs the authoritative authentication check without exposing credentials to MainFlow.
    return CodexPreflightResult(str(settings.executable), output, "checked_on_first_request")

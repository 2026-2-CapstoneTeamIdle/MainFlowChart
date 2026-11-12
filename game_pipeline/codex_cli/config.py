"""Environment configuration for the Codex CLI game-development harness."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path


def resolve_game_builder() -> str:
    value = os.environ.get("MAINFLOW_GAME_BUILDER", "pipeline").strip().lower()
    aliases = {
        "codex": "codex_cli",
        "codex-cli": "codex_cli",
        "claude": "claude_code",
        "claude-code": "claude_code",
        "default": "pipeline",
    }
    normalized = aliases.get(value, value)
    if normalized not in {"pipeline", "codex_cli", "claude_code"}:
        raise ValueError("MAINFLOW_GAME_BUILDER must be 'pipeline', 'codex_cli', or 'claude_code'")
    return normalized


@dataclass(frozen=True)
class CodexHarnessSettings:
    executable: Path
    model: str | None
    reasoning_effort: str | None
    invocation_timeout_seconds: int
    total_timeout_seconds: int
    max_repairs: int
    service_tier: str | None = None

    @classmethod
    def from_environment(cls) -> CodexHarnessSettings:
        configured = os.environ.get("MAINFLOW_CODEX_CLI_PATH", "").strip()
        discovered = configured or _discover_codex_executable()
        if not discovered:
            raise FileNotFoundError(
                "Codex CLI was not found. Install Codex and ensure 'codex' is on PATH, or set "
                "MAINFLOW_CODEX_CLI_PATH."
            )
        executable = Path(discovered).resolve()
        timeout = _integer_environment("MAINFLOW_CODEX_TIMEOUT_SECONDS", 1800, 60, 7200)
        total_timeout = _integer_environment(
            "MAINFLOW_CODEX_TOTAL_TIMEOUT_SECONDS", 7200, timeout, 21600
        )
        max_repairs = _integer_environment("MAINFLOW_CODEX_MAX_REPAIRS", 6, 0, 10)
        model = os.environ.get("MAINFLOW_CODEX_MODEL", "gpt-5.6-luna").strip() or None
        reasoning = os.environ.get("MAINFLOW_CODEX_REASONING_EFFORT", "medium").strip() or None
        if reasoning not in {None, "low", "medium", "high", "xhigh", "max", "ultra"}:
            raise ValueError("MAINFLOW_CODEX_REASONING_EFFORT has an unsupported value")
        service_tier = os.environ.get("MAINFLOW_CODEX_SERVICE_TIER", "").strip() or None
        if service_tier not in {None, "fast"}:
            raise ValueError("MAINFLOW_CODEX_SERVICE_TIER must be 'fast' when configured")
        return cls(executable, model, reasoning, timeout, total_timeout, max_repairs, service_tier)


def _discover_codex_executable() -> str | None:
    """Find standalone installs and the newest version bundled with Codex Desktop."""

    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        desktop_bin = Path(local_app_data) / "OpenAI" / "Codex" / "bin"
        versioned = [path for path in desktop_bin.glob("*/codex.exe") if path.is_file()]
        if versioned:
            newest = max(versioned, key=lambda path: path.stat().st_mtime_ns)
            return str(newest)
    on_path = shutil.which("codex")
    if on_path:
        return on_path
    if local_app_data:
        desktop_shim = Path(local_app_data) / "OpenAI" / "Codex" / "bin" / "codex.exe"
        if desktop_shim.is_file():
            return str(desktop_shim)
    return None


def _integer_environment(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError as error:
        raise ValueError(f"{name} must be an integer") from error
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value

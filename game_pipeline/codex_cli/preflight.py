"""Read-only installation and login checks for Codex CLI."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass

from game_pipeline.codex_cli.config import CodexHarnessSettings


@dataclass(frozen=True)
class CodexPreflightResult:
    executable: str
    version: str
    login_status: str

    def to_dict(self) -> dict[str, str]:
        return {
            "executable": self.executable,
            "version": self.version,
            "login_status": self.login_status,
        }


def run_codex_preflight(settings: CodexHarnessSettings) -> CodexPreflightResult:
    version = _run(settings, ["--version"], "CODEX_VERSION_CHECK_FAILED")
    login = _run(settings, ["login", "status"], "CODEX_NOT_LOGGED_IN")
    return CodexPreflightResult(str(settings.executable), version, login)


def _run(settings: CodexHarnessSettings, arguments: list[str], code: str) -> str:
    try:
        result = subprocess.run(
            [str(settings.executable), *arguments],
            env=_login_environment(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(f"{code}: {error}") from error
    output = (result.stdout + "\n" + result.stderr).strip()
    if result.returncode != 0:
        raise RuntimeError(f"{code}: {output or f'exit code {result.returncode}'}")
    return output


def _login_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for name in ("OPENAI_API_KEY", "CODEX_ACCESS_TOKEN"):
        environment.pop(name, None)
    return environment

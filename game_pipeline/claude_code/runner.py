"""Non-interactive Claude Code runner compatible with the shared game harness."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from game_pipeline.claude_code.config import ClaudeCodeHarnessSettings
from game_pipeline.codex_cli.runner import SECRET_ENVIRONMENT_NAMES, CodexCliResult


class ClaudeCodeCliRunner:
    def __init__(self, settings: ClaudeCodeHarnessSettings) -> None:
        self.settings = settings

    def run(
        self,
        *,
        project_root: Path,
        prompt: str,
        schema: dict[str, Any],
        audit_directory: Path,
        sandbox: str = "workspace-write",
    ) -> CodexCliResult:
        root = project_root.resolve()
        if not root.is_dir():
            raise FileNotFoundError(f"Claude Code project root does not exist: {root}")
        audit_directory.mkdir(parents=True, exist_ok=True)
        prompt_path = audit_directory / "prompt.txt"
        schema_path = audit_directory / "completion.schema.json"
        answer_path = audit_directory / "result.json"
        events_path = audit_directory / "events.json"
        stderr_path = audit_directory / "stderr.log"
        prompt_path.write_text(prompt, encoding="utf-8", newline="\n")
        schema_json = json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
        schema_path.write_text(
            json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

        command = [
            str(self.settings.executable),
            "-p",
            "--output-format",
            "json",
            "--json-schema",
            schema_json,
            "--max-turns",
            str(self.settings.max_turns),
        ]
        if sandbox != "read-only":
            command.extend(["--permission-mode", self.settings.permission_mode])
        else:
            command.extend(["--permission-mode", "plan"])
        if self.settings.model:
            command.extend(["--model", self.settings.model])

        started = time.monotonic()
        try:
            process = subprocess.run(
                command,
                input=prompt,
                cwd=root,
                env=_claude_environment(),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.settings.invocation_timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            events_path.write_text(error.stdout or "", encoding="utf-8")
            stderr_path.write_text(error.stderr or "", encoding="utf-8")
            raise TimeoutError(
                f"CLAUDE_PROCESS_TIMEOUT after {self.settings.invocation_timeout_seconds}s"
            ) from error
        events_path.write_text(process.stdout, encoding="utf-8")
        stderr_path.write_text(process.stderr, encoding="utf-8")
        if process.returncode != 0:
            detail = process.stderr.strip() or process.stdout.strip()
            raise RuntimeError(f"CLAUDE_AGENT_FAILED ({process.returncode}): {detail[:4000]}")
        response, event = _parse_claude_result(process.stdout)
        answer_path.write_text(
            json.dumps(response, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return CodexCliResult(
            process.returncode,
            time.monotonic() - started,
            response,
            (event,),
            audit_directory,
        )


def _parse_claude_result(stdout: str) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"CLAUDE_OUTPUT_INVALID: stdout was not JSON: {error}") from error
    if not isinstance(envelope, dict):
        raise TypeError("CLAUDE_OUTPUT_INVALID: response envelope must be an object")
    if envelope.get("is_error"):
        raise RuntimeError(f"CLAUDE_AGENT_FAILED: {envelope.get('result', 'unknown error')}")
    structured = envelope.get("structured_output")
    if not isinstance(structured, dict):
        raw = envelope.get("result")
        if isinstance(raw, str):
            try:
                structured = json.loads(raw)
            except json.JSONDecodeError as error:
                raise RuntimeError(
                    "CLAUDE_OUTPUT_INVALID: structured_output was absent and result was not JSON"
                ) from error
    if not isinstance(structured, dict):
        raise TypeError("CLAUDE_OUTPUT_INVALID: final response must be an object")
    return structured, envelope


def _claude_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for name in SECRET_ENVIRONMENT_NAMES | {"ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"}:
        environment.pop(name, None)
    return environment

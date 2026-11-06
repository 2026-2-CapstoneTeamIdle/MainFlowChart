"""Safe non-interactive Codex CLI process runner with durable JSONL evidence."""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from game_pipeline.codex_cli.config import CodexHarnessSettings

SECRET_ENVIRONMENT_NAMES = {
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "VASTAI_INFERENCE_API_KEY",
    "ELEVENLABS_API_KEY",
    "CODEX_ACCESS_TOKEN",
}


@dataclass(frozen=True)
class CodexCliResult:
    exit_code: int
    elapsed_seconds: float
    final_response: dict[str, Any]
    events: tuple[dict[str, Any], ...]
    audit_directory: Path


class CodexCliRunner:
    def __init__(self, settings: CodexHarnessSettings) -> None:
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
            raise FileNotFoundError(f"Codex project root does not exist: {root}")
        audit_directory.mkdir(parents=True, exist_ok=True)
        prompt_path = audit_directory / "prompt.txt"
        schema_path = audit_directory / "completion.schema.json"
        answer_path = audit_directory / "result.json"
        events_path = audit_directory / "events.jsonl"
        stderr_path = audit_directory / "stderr.log"
        prompt_path.write_text(prompt, encoding="utf-8", newline="\n")
        schema_path.write_text(
            json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

        command = [
            str(self.settings.executable),
            "exec",
            "--cd",
            str(root),
            "--sandbox",
            sandbox,
            "--json",
            "--ignore-rules",
            "--output-schema",
            str(schema_path),
            "--output-last-message",
            str(answer_path),
        ]
        if self.settings.model:
            command.extend(["--model", self.settings.model])
        if self.settings.reasoning_effort:
            command.extend(["--config", f"model_reasoning_effort={self.settings.reasoning_effort}"])
        command.append("-")

        started = time.monotonic()
        try:
            process = subprocess.run(
                command,
                input=prompt,
                cwd=root,
                env=_codex_environment(),
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
                f"CODEX_PROCESS_TIMEOUT after {self.settings.invocation_timeout_seconds}s"
            ) from error
        events_path.write_text(process.stdout, encoding="utf-8")
        stderr_path.write_text(process.stderr, encoding="utf-8")
        events = _parse_jsonl(process.stdout)
        if process.returncode != 0:
            detail = process.stderr.strip() or _last_event_message(events)
            raise RuntimeError(f"CODEX_AGENT_FAILED ({process.returncode}): {detail}")
        if not answer_path.is_file():
            raise RuntimeError("CODEX_OUTPUT_INVALID: result.json was not created")
        try:
            response = json.loads(answer_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise RuntimeError(f"CODEX_OUTPUT_INVALID: {error}") from error
        if not isinstance(response, dict):
            raise TypeError("CODEX_OUTPUT_INVALID: final response must be an object")
        return CodexCliResult(
            process.returncode,
            time.monotonic() - started,
            response,
            tuple(events),
            audit_directory,
        )


def _codex_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for name in SECRET_ENVIRONMENT_NAMES:
        environment.pop(name, None)
    return environment


def _parse_jsonl(value: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    invalid: list[str] = []
    for line in value.splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            invalid.append(line[:200])
            continue
        if isinstance(item, dict):
            events.append(item)
    if invalid and not events:
        raise RuntimeError("CODEX_OUTPUT_INVALID: stdout was not JSONL")
    return events


def _last_event_message(events: list[dict[str, Any]]) -> str:
    for event in reversed(events):
        item = event.get("item")
        if isinstance(item, dict):
            for key in ("text", "message", "command"):
                value = item.get(key)
                if isinstance(value, str) and value:
                    return value[:1000]
    return "no diagnostic event was emitted"

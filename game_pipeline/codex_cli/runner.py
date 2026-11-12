"""Safe non-interactive Codex CLI process runner with durable JSONL evidence."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
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
        process = _stream_codex_process(
            command=command,
            prompt=prompt,
            cwd=root,
            environment=_codex_environment(),
            timeout_seconds=self.settings.invocation_timeout_seconds,
            events_path=events_path,
            stderr_path=stderr_path,
        )
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


@dataclass(frozen=True)
class _ProcessOutput:
    returncode: int
    stdout: str
    stderr: str


class _AgentProgressReporter:
    """Turn verbose CLI JSONL into a few user-facing workflow milestones."""

    def __init__(self) -> None:
        self.started = time.monotonic()
        self.last_message_at = 0.0
        self.stage = "context"
        self.seen_stages: set[str] = set()
        self.stage_order = {"context": 0, "plan": 1, "edit": 2, "validate": 3, "finalize": 4}

    def observe(self, event: dict[str, Any]) -> None:
        event_type = str(event.get("type", ""))
        item = event.get("item")
        item = item if isinstance(item, dict) else {}
        item_type = str(item.get("type", ""))
        command = str(item.get("command", "")).lower()

        if event_type in {"thread.started", "turn.started"}:
            self.emit("context", "Codex가 Unity 프로젝트 구조와 요구사항을 분석하고 있습니다.")
        elif item_type in {"reasoning", "analysis"}:
            self.emit("plan", "구현 계획과 파일 간 연결 관계를 정리하고 있습니다.")
        elif item_type in {"file_change", "file_changes", "patch"}:
            self.emit("edit", "Unity 스크립트와 설정을 작성·수정하고 있습니다.")
        elif item_type in {"command_execution", "command"}:
            if any(token in command for token in ("apply_patch", "write", "move-item")):
                self.emit("edit", "Unity 스크립트와 설정을 작성·수정하고 있습니다.")
            elif any(
                token in command
                for token in (
                    "pytest",
                    "dotnet test",
                    "-batchmode",
                    "compileall",
                    "format_repo.py --check",
                )
            ):
                self.emit("validate", "변경된 코드와 요구사항 연결을 자체 점검하고 있습니다.")
            elif any(token in command for token in ("rg ", "get-content", "find ", "ls ")):
                self.emit("context", "관련 Unity 소스와 계약 파일을 읽고 있습니다.")
        elif event_type == "turn.completed":
            self.emit("finalize", "Codex 구현 결과와 변경 파일 목록을 정리했습니다.", force=True)

    def heartbeat(self) -> None:
        now = time.monotonic()
        if now - self.last_message_at < 60:
            return
        elapsed_seconds = max(1, int(now - self.started))
        elapsed_minutes, remaining_seconds = divmod(elapsed_seconds, 60)
        labels = {
            "context": "프로젝트 문맥 분석",
            "plan": "구현 계획 수립",
            "edit": "Unity 코드 작성·수정",
            "validate": "변경 내용 자체 점검",
            "finalize": "결과 정리",
        }
        self.emit(
            self.stage,
            (
                "Codex가 계속 처리 중입니다: "
                f"{labels[self.stage]} ({elapsed_minutes}분 {remaining_seconds:02d}초 경과)."
            ),
            force=True,
        )

    def emit(self, stage: str, message: str, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and self.stage_order[stage] < self.stage_order[self.stage]:
            return
        if not force and stage in self.seen_stages:
            return
        self.stage = stage
        self.seen_stages.add(stage)
        self.last_message_at = now
        print(f"[AGENT][{stage}] {message}", flush=True)


def _stream_codex_process(
    *,
    command: list[str],
    prompt: str,
    cwd: Path,
    environment: dict[str, str],
    timeout_seconds: int,
    events_path: Path,
    stderr_path: Path,
) -> _ProcessOutput:
    """Capture durable evidence while forwarding only curated live progress."""

    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=cwd,
        env=environment,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None

    stdout_queue: queue.Queue[str | None] = queue.Queue()
    stderr_lines: list[str] = []

    def read_stdout() -> None:
        for line in process.stdout:
            stdout_queue.put(line)
        stdout_queue.put(None)

    def read_stderr() -> None:
        stderr_lines.extend(process.stderr.readlines())

    stdout_thread = threading.Thread(target=read_stdout, daemon=True)
    stderr_thread = threading.Thread(target=read_stderr, daemon=True)
    stdout_thread.start()
    stderr_thread.start()
    try:
        process.stdin.write(prompt)
        process.stdin.close()
    except BrokenPipeError:
        pass

    reporter = _AgentProgressReporter()
    reporter.emit("context", "Codex 작업 세션을 시작하고 프로젝트 문맥을 준비합니다.")
    stdout_lines: list[str] = []
    deadline = time.monotonic() + timeout_seconds
    with events_path.open("w", encoding="utf-8", newline="\n") as event_file:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                process.kill()
                process.wait()
                stderr_thread.join(timeout=2)
                stderr_path.write_text("".join(stderr_lines), encoding="utf-8")
                raise TimeoutError(f"CODEX_PROCESS_TIMEOUT after {timeout_seconds}s")
            try:
                line = stdout_queue.get(timeout=min(15, remaining))
            except queue.Empty:
                reporter.heartbeat()
                continue
            if line is None:
                break
            stdout_lines.append(line)
            event_file.write(line)
            event_file.flush()
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                reporter.observe(event)
            reporter.heartbeat()

    returncode = process.wait()
    stdout_thread.join(timeout=2)
    stderr_thread.join(timeout=2)
    stderr = "".join(stderr_lines)
    stderr_path.write_text(stderr, encoding="utf-8")
    return _ProcessOutput(returncode, "".join(stdout_lines), stderr)


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

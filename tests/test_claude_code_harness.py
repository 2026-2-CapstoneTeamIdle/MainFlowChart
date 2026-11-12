from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from game_pipeline.claude_code.config import ClaudeCodeHarnessSettings
from game_pipeline.claude_code.runner import ClaudeCodeCliRunner
from game_pipeline.codex_cli.harness import COMPLETION_SCHEMA, _write_project_instructions


def _settings(executable: Path) -> ClaudeCodeHarnessSettings:
    return ClaudeCodeHarnessSettings(
        executable=executable,
        model="sonnet",
        reasoning_effort="high",
        invocation_timeout_seconds=60,
        total_timeout_seconds=120,
        max_repairs=2,
        max_turns=40,
        permission_mode="acceptEdits",
    )


def _completion() -> dict[str, object]:
    return {
        "status": "completed",
        "summary": "implemented",
        "changed_files": ["Assets/Game.cs"],
        "implemented_features": ["movement"],
        "tests_run": ["static inspection"],
        "unresolved_requirements": [],
        "recommended_validation": ["Unity batch mode"],
    }


def test_claude_runner_uses_print_mode_schema_and_user_login(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "unity"
    project.mkdir()
    executable = tmp_path / "claude.cmd"
    executable.write_bytes(b"")
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        envelope = {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "structured_output": _completion(),
        }
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(envelope), stderr="")

    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-leak")
    with patch("game_pipeline.claude_code.runner.subprocess.run", side_effect=fake_run):
        result = ClaudeCodeCliRunner(_settings(executable)).run(
            project_root=project,
            prompt="implement",
            schema=COMPLETION_SCHEMA,
            audit_directory=tmp_path / "audit",
        )

    command = captured["command"]
    assert "-p" in command
    assert command[command.index("--output-format") + 1] == "json"
    assert command[command.index("--permission-mode") + 1] == "acceptEdits"
    assert command[command.index("--model") + 1] == "sonnet"
    assert command[command.index("--effort") + 1] == "high"
    assert json.loads(command[command.index("--json-schema") + 1]) == COMPLETION_SCHEMA
    assert captured["kwargs"]["cwd"] == project.resolve()
    assert "ANTHROPIC_API_KEY" not in captured["kwargs"]["env"]
    assert result.final_response == _completion()


def test_claude_writes_claude_md_instructions(tmp_path: Path) -> None:
    project = tmp_path / "unity"
    project.mkdir()
    design = {"codex_harness_requirements": ["wall_climb"]}
    request = {"condition": "벽을 타는 게임", "genre": "플랫포머", "viewpoint": "사이드뷰"}

    _write_project_instructions(
        project,
        design,  # type: ignore[arg-type]
        request,  # type: ignore[arg-type]
        agent_label="Claude Code",
        filename="CLAUDE.md",
    )

    instructions = (project / "CLAUDE.md").read_text(encoding="utf-8")
    assert "Gameplay modules and mechanics assigned to Claude Code" in instructions
    assert "compatibility scaffold, not a finished genre template" in instructions
    assert "Do not launch Unity Editor" in instructions

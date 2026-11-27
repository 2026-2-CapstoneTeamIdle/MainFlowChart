"""Tests for the direct, one-prompt Codex experiment."""

from __future__ import annotations

import json
from pathlib import Path

from tools import run_codex_workbook_experiment as experiment

REQUEST = {
    "genre": "플랫포머",
    "viewpoint": "사이드뷰",
    "image_style": "픽셀 아트",
    "mood_style": "어두운 분위기",
    "condition": "검을 쓰지 않는다.\n시간의 파편 12개를 수집한다.",
}


def test_prompt_contains_five_workbook_values_without_rewriting_condition() -> None:
    prompt = experiment.create_prompt(REQUEST)

    for value in REQUEST.values():
        assert value in prompt
    assert prompt.count(REQUEST["condition"]) == 1
    assert prompt.endswith(REQUEST["condition"] + "\n")


def test_codex_usage_counts_cached_input_once(tmp_path: Path) -> None:
    events = tmp_path / "codex_events.jsonl"
    events.write_text(
        "\n".join(
            (
                json.dumps({"type": "turn.started"}),
                json.dumps(
                    {
                        "type": "turn.completed",
                        "usage": {
                            "input_tokens": 100,
                            "cached_input_tokens": 60,
                            "output_tokens": 20,
                            "reasoning_output_tokens": 5,
                        },
                    }
                ),
            )
        ),
        encoding="utf-8",
    )

    usage = experiment.collect_codex_usage(events)

    assert usage["total_tokens"] == 120
    assert usage["cached_input_tokens"] == 60
    assert usage["token_usage_status"] == "complete"


def test_summary_uses_codex_completion_and_real_build_verdict() -> None:
    rows = [
        {
            "prompt_id": "P01",
            "codex_status": "completed",
            "build_status": "passed",
            "generation_seconds": "100",
            "total_tokens": "120",
            "token_usage_status": "complete",
        },
        {
            "prompt_id": "P01",
            "codex_status": "failed",
            "build_status": "passed",
            "generation_seconds": "200",
            "total_tokens": "30",
            "token_usage_status": "partial",
        },
        {
            "prompt_id": "P01",
            "codex_status": "not_started",
            "build_status": "not_attempted",
        },
    ]

    result = experiment.summarize(rows)["overall"]

    assert result["build_success"] == {
        "passed": 1,
        "rate": 1 / 3,
        "attempted": 2,
        "attempted_rate": 0.5,
    }
    assert result["generation_seconds"]["mean"] == 150
    assert result["total_tokens"]["measured"] == 1


def test_trial_invokes_codex_once_without_mainflow(tmp_path: Path, monkeypatch) -> None:
    commands: list[list[str]] = []

    def fake_run_command(command, *, stdout_file, prompt=None, **kwargs):
        commands.append(command)
        if "-createProject" in command:
            project = Path(command[command.index("-createProject") + 1])
            settings = project / "ProjectSettings"
            settings.mkdir(parents=True)
            (settings / "ProjectVersion.txt").write_text("m_EditorVersion: 6000.0.71f1")
            return 0, 8.0, False
        assert command[1] == "exec"
        assert prompt == experiment.create_prompt(REQUEST)
        stdout_file.write_text(
            json.dumps(
                {
                    "type": "turn.completed",
                    "usage": {"input_tokens": 10, "output_tokens": 5},
                }
            ),
            encoding="utf-8",
        )
        return 0, 12.0, False

    monkeypatch.setattr(experiment, "run_command", fake_run_command)
    monkeypatch.setattr(
        experiment,
        "run_player_build",
        lambda *args, **kwargs: {
            "player_build_status": "passed",
            "player_build_seconds": 4.0,
            "player_build_exit_code": 0,
            "player_build_error": "",
            "player_build_log_file": str(tmp_path / "build.log"),
            "player_build_output": str(tmp_path / "Game.exe"),
        },
    )
    row = experiment.run_trial(
        trial_id="P01-01",
        prompt_id="P01",
        repeat=1,
        request=REQUEST,
        editor=tmp_path / "Unity.exe",
        codex=tmp_path / "codex.cmd",
        model="gpt-5.6-luna",
        reasoning_effort="medium",
        fast_mode=False,
        trial_dir=tmp_path / "trial",
        create_timeout_minutes=1,
        generation_timeout_minutes=1,
        build_timeout_minutes=1,
    )

    assert len(commands) == 2
    assert commands[1][1] == "exec"
    assert "mainflow.run_flow" not in commands[1]
    assert row["generation_seconds"] == "12.0"
    assert row["build_status"] == "passed"
    assert row["total_tokens"] == "15"

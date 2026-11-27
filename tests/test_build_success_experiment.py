"""Metrics for repeatable headless game build experiments."""

from __future__ import annotations

import json
import sys

from tools.unity_player_build import (
    build_command,
    classify_player_build,
    resolve_editor,
    run_player_build,
)

from tools.build_success_experiment import (
    DEFAULT_PRICING,
    collect_codex_token_usage,
    collect_checklist_progress,
    collect_provider_usage,
    extract_metrics,
    initial_source_preflight_failed,
    main,
    summarize,
)


def test_initial_source_failure_stops_a_batch_without_matching_other_failures(tmp_path) -> None:
    project = tmp_path / "project"
    failure = project / "validation" / "game_generation_failure.json"
    failure.parent.mkdir(parents=True)
    failure.write_text(
        json.dumps({"message": "UNITY_INITIAL_SOURCE_INVALID before agent implementation"}),
        encoding="utf-8",
    )
    assert initial_source_preflight_failed(project)
    failure.write_text(json.dumps({"message": "UNITY_RUNTIME_TEST_FAILED"}), encoding="utf-8")
    assert not initial_source_preflight_failed(project)


def test_extract_metrics_keeps_compile_and_runtime_separate_from_final_review() -> None:
    payload = {
        "project_id": "trial-1",
        "game_validation": {
            "status": "failed",
            "checks": [
                {"criterion_id": "unity.batchmode", "passed": True},
                {"criterion_id": "unity.runtime_smoke", "passed": False},
            ],
            "issues": [{"code": "UNITY_RUNTIME_TEST_FAILED"}],
        },
        "final_validation": {
            "status": "failed",
            "issues": [{"code": "FINAL_REQUIREMENT_UNSATISFIED"}],
        },
        "game_validator_ai": {"status": "failed"},
    }

    result = extract_metrics(payload, "full")

    assert result["project_id"] == "trial-1"
    assert result["compile_passed"] is True
    assert result["play_mode_passed"] is False
    assert result["final_validation_passed"] is False
    assert result["quality_review_passed"] is False
    assert result["failure_codes"] == ("UNITY_RUNTIME_TEST_FAILED;FINAL_REQUIREMENT_UNSATISFIED")


def test_summarize_counts_missing_results_as_failures() -> None:
    rows = [
        {
            "request": "platformer.json",
            "compile_passed": "True",
            "play_mode_passed": "True",
            "player_build_status": "passed",
            "player_build_seconds": "20",
            "elapsed_seconds": "60",
            "total_tokens": "300",
            "token_usage_status": "complete",
            "image_total_tokens": "120",
            "image_usage_status": "complete",
            "elevenlabs_character_cost": "42",
            "elevenlabs_usage_status": "complete",
            "image_estimated_usd": "0.005",
            "image_cost_status": "estimated",
            "elevenlabs_estimated_usd": "0.15",
            "elevenlabs_cost_status": "estimated",
        },
        {
            "request": "platformer.json",
            "compile_passed": "False",
            "play_mode_passed": "False",
            "player_build_status": "failed",
            "player_build_seconds": "40",
            "elapsed_seconds": "120",
            "total_tokens": "50",
            "token_usage_status": "partial",
            "image_total_tokens": "50",
            "image_usage_status": "partial",
            "elevenlabs_character_cost": "10",
            "elevenlabs_usage_status": "partial",
            "image_estimated_usd": "0.001",
            "image_cost_status": "partial_estimate",
            "elevenlabs_estimated_usd": "0.02",
            "elevenlabs_cost_status": "partial_estimate",
        },
    ]

    result = summarize(rows, "game-test")

    assert result["overall"]["runs"] == 2
    assert result["overall"]["build_success"] == {
        "passed": 1,
        "rate": 0.5,
        "attempted": 2,
        "attempted_rate": 0.5,
    }
    assert result["overall"]["compile_passed"] == {"passed": 1, "rate": 0.5}
    assert result["by_request"]["platformer.json"]["play_mode_passed"]["rate"] == 0.5
    assert result["overall"]["elapsed_seconds"]["median"] == 90
    assert result["overall"]["player_build_seconds"]["median"] == 30
    assert result["overall"]["total_tokens"] == {"measured": 1, "mean": 300, "median": 300}
    assert result["overall"]["image_total_tokens"] == {
        "measured": 1,
        "mean": 120,
        "median": 120,
    }
    assert result["overall"]["elevenlabs_character_cost"] == {
        "measured": 1,
        "mean": 42,
        "median": 42,
    }
    assert result["overall"]["image_estimated_usd"]["mean"] == 0.005
    assert result["overall"]["elevenlabs_estimated_usd"]["mean"] == 0.15
    assert "final_validation_passed" not in result["overall"]


def test_codex_token_usage_counts_completed_turns_without_double_counting_cache(tmp_path) -> None:
    project = tmp_path / "project"
    first = project / "validation" / "codex" / "feature_analysis" / "events.jsonl"
    second = project / "validation" / "codex" / "repair" / "events.jsonl"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_text(
        "\n".join(
            json.dumps(event)
            for event in (
                {"type": "turn.started"},
                {
                    "type": "turn.completed",
                    "usage": {
                        "input_tokens": 100,
                        "cached_input_tokens": 80,
                        "output_tokens": 20,
                        "reasoning_output_tokens": 5,
                    },
                },
            )
        ),
        encoding="utf-8",
    )
    second.write_text(
        json.dumps(
            {
                "type": "turn.completed",
                "usage": {"input_tokens": 40, "cached_input_tokens": 0, "output_tokens": 10},
            }
        ),
        encoding="utf-8",
    )

    result = collect_codex_token_usage(project)

    assert result == {
        "input_tokens": 140,
        "cached_input_tokens": 80,
        "output_tokens": 30,
        "reasoning_output_tokens": 5,
        "total_tokens": 170,
        "token_usage_status": "complete",
        "codex_event_files": 2,
    }


def test_codex_token_usage_marks_incomplete_event_files_partial(tmp_path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "validation").mkdir()
    (project / "validation" / "events.jsonl").write_text(
        json.dumps({"type": "turn.completed", "usage": {"input_tokens": 5, "output_tokens": 2}}),
        encoding="utf-8",
    )
    incomplete = project / "validation" / "repair" / "events.jsonl"
    incomplete.parent.mkdir()
    incomplete.write_text('{"type":"turn.started"}\n', encoding="utf-8")

    assert collect_codex_token_usage(project)["token_usage_status"] == "partial"
    assert collect_codex_token_usage(tmp_path / "missing")["token_usage_status"] == "missing"


def test_dry_run_prints_trials_without_creating_output(tmp_path, monkeypatch, capsys) -> None:
    request_file = tmp_path / "platformer.json"
    request_file.write_text(
        json.dumps(
            {
                "image_style": "Pixel Art",
                "mood_style": "Fantasy",
                "genre": "플랫포머",
                "viewpoint": "사이드뷰",
                "condition": "Create a short platformer.",
            }
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "results"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "build_success_experiment.py",
            "--request-file",
            str(request_file),
            "--repeats",
            "3",
            "--output-dir",
            str(output_dir),
            "--dry-run",
        ],
    )

    assert main() == 0
    assert len(capsys.readouterr().out.strip().splitlines()) == 3
    assert not output_dir.exists()


def test_provider_usage_sums_requests_and_keeps_unreported_music_unknown(tmp_path) -> None:
    project = tmp_path / "project"
    usage_root = project / "validation" / "api_usage"
    usage_root.mkdir(parents=True)
    (usage_root / "openai_image.jsonl").write_text(
        "\n".join(
            json.dumps(event)
            for event in (
                {
                    "status": "success",
                    "model": "gpt-image-2.5-sunburst",
                    "usage": {
                        "input_tokens": 30,
                        "input_text_tokens": 10,
                        "input_image_tokens": 20,
                        "output_tokens": 70,
                        "output_text_tokens": 0,
                        "output_image_tokens": 70,
                        "total_tokens": 100,
                    },
                },
                {
                    "status": "success",
                    "model": "gpt-image-2.5-sunburst",
                    "usage": {
                        "input_tokens": 40,
                        "input_text_tokens": 15,
                        "input_image_tokens": 25,
                        "output_tokens": 80,
                        "output_text_tokens": 0,
                        "output_image_tokens": 80,
                        "total_tokens": 120,
                    },
                },
            )
        ),
        encoding="utf-8",
    )
    (usage_root / "elevenlabs.jsonl").write_text(
        "\n".join(
            json.dumps(event)
            for event in (
                {
                    "endpoint": "/v1/sound-generation",
                    "status": "success",
                    "character_cost": "42",
                    "requested_duration_seconds": 2,
                },
                {
                    "endpoint": "/v1/music",
                    "status": "success",
                    "character_cost": None,
                    "song_id": "song-1",
                    "requested_duration_seconds": 60,
                },
            )
        ),
        encoding="utf-8",
    )

    result = collect_provider_usage(project, pricing=json.loads(DEFAULT_PRICING.read_text()))

    assert result["image_api_requests"] == 2
    assert result["image_total_tokens"] == 220
    assert result["image_input_image_tokens"] == 45
    assert result["image_usage_status"] == "complete"
    assert result["image_breakdown_status"] == "complete"
    assert result["image_estimated_usd"] == "0.004985"
    assert result["image_cost_status"] == "estimated"
    assert result["elevenlabs_api_requests"] == 2
    assert result["elevenlabs_sfx_character_cost"] == "42"
    assert result["elevenlabs_music_character_cost"] == ""
    assert result["elevenlabs_character_cost"] == "42"
    assert result["elevenlabs_music_generated_count"] == 1
    assert result["elevenlabs_music_requested_seconds"] == "60"
    assert result["elevenlabs_usage_status"] == "partial"
    assert result["elevenlabs_estimated_usd"] == "0.154"
    assert result["elevenlabs_cost_status"] == "estimated"


def test_provider_usage_does_not_treat_unreported_attempt_as_zero(tmp_path) -> None:
    project = tmp_path / "project"
    usage_root = project / "validation" / "api_usage"
    usage_root.mkdir(parents=True)
    (usage_root / "openai_image.jsonl").write_text(
        json.dumps({"status": "error", "usage_status": "unknown"}), encoding="utf-8"
    )
    (usage_root / "elevenlabs.jsonl").write_text(
        json.dumps({"event": "provider_selected", "backend": "procedural"}), encoding="utf-8"
    )

    result = collect_provider_usage(project)

    assert result["image_api_requests"] == 1
    assert result["image_total_tokens"] == ""
    assert result["image_usage_status"] == "partial"
    assert result["elevenlabs_usage_status"] == "not_used"
    assert result["elevenlabs_character_cost"] == 0


def test_missing_provider_ledger_is_not_mistaken_for_zero_usage(tmp_path) -> None:
    project = tmp_path / "project"
    project.mkdir()

    result = collect_provider_usage(project)

    assert result["image_usage_status"] == "missing"
    assert result["elevenlabs_usage_status"] == "missing"
    assert result["image_total_tokens"] == ""

    skipped = collect_provider_usage(None, assets_skipped=True)
    assert skipped["image_usage_status"] == "not_used"
    assert skipped["elevenlabs_usage_status"] == "not_used"
    assert skipped["image_total_tokens"] == 0


def test_checklist_progress_distinguishes_generated_from_executed(tmp_path) -> None:
    project = tmp_path / "project"
    data = project / "data"
    data.mkdir(parents=True)
    (data / "logic_analysis.json").write_text(
        json.dumps({"features": [{"feature_id": "feature-01"}]}), encoding="utf-8"
    )
    generated = project / "validation/feature_checklists/generated"
    generated.mkdir(parents=True)
    (generated / "checklist.json").write_text(
        json.dumps(
            {
                "feature_checklists": [
                    {
                        "feature_id": "feature-01",
                        "criteria": [
                            {"criterion_id": "DFC001_01"},
                            {"criterion_id": "DFC001_02"},
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    assert collect_checklist_progress(project)["dynamic_test_verdict"] == "checklist_created"
    source = generated / "feature-01/GeneratedFeatureChecklist_DFC001.cs"
    source.parent.mkdir()
    source.write_text("test", encoding="utf-8")
    assert collect_checklist_progress(project)["dynamic_test_verdict"] == "test_code_created"
    checked = project / "validation/feature_checklists/checked/results.json"
    checked.parent.mkdir()
    checked.write_text(
        json.dumps(
            {
                "attempts": [
                    {
                        "results": [
                            {"feature_id": "DFC001_01", "status": "passed"},
                            {
                                "feature_id": "DFC001_02",
                                "status": "error",
                                "failure_kind": "test_source",
                            },
                        ]
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    progress = collect_checklist_progress(project)
    assert progress["approved_feature_count"] == 1
    assert progress["checklist_generated_feature_count"] == 1
    assert progress["unity_test_generated_feature_count"] == 1
    assert progress["dynamic_test_planned_item_count"] == 2
    assert progress["dynamic_test_executed_item_count"] == 1
    assert progress["dynamic_test_verdict"] == "executed_partial"


def test_player_build_command_targets_windows_and_records_log(tmp_path) -> None:
    editor = tmp_path / "Unity.exe"
    project = tmp_path / "project"
    executable = tmp_path / "output" / "Game.exe"
    log_file = tmp_path / "build.log"

    command = build_command(editor, project, executable, log_file)

    assert command[0] == str(editor)
    assert command[command.index("-buildTarget") + 1] == "StandaloneWindows64"
    assert command[command.index("-projectPath") + 1] == str(project)
    assert command[command.index("-experimentOutput") + 1] == str(executable)
    assert command[command.index("-logFile") + 1] == str(log_file)


def test_player_build_missing_project_and_editor_are_not_game_failures(tmp_path) -> None:
    assert run_player_build(None, tmp_path / "trial")["player_build_status"] == "not_attempted"
    project = tmp_path / "project"
    settings = project / "ProjectSettings"
    settings.mkdir(parents=True)
    (settings / "ProjectVersion.txt").write_text("m_EditorVersion: 6000.0.71f1")
    assert resolve_editor(project, str(tmp_path / "missing.exe")) is None
    result = run_player_build(
        project,
        tmp_path / "trial",
        editor_path=str(tmp_path / "missing.exe"),
    )
    assert result["player_build_status"] == "infrastructure_error"
    assert result["player_build_error"] == "Unity Editor not found"


def test_build_success_uses_actual_player_build_verdict() -> None:
    rows = [
        {
            "request": "P01.json",
            "compile_passed": "True",
            "play_mode_passed": "True",
            "player_build_status": "failed",
        },
        {
            "request": "P01.json",
            "compile_passed": "False",
            "play_mode_passed": "False",
            "player_build_status": "passed",
        },
        {"request": "P01.json", "player_build_status": "infrastructure_error"},
    ]

    result = summarize(rows, "game-test")["overall"]["build_success"]

    assert result == {"passed": 1, "rate": 1 / 3, "attempted": 2, "attempted_rate": 0.5}


def test_player_build_requires_success_marker_and_executable() -> None:
    assert classify_player_build(0, "EXPERIMENT_BUILD_OK:C:/build/Game.exe", True) == "passed"
    assert classify_player_build(0, "EXPERIMENT_BUILD_OK:C:/build/Game.exe", False) == "failed"
    assert classify_player_build(0, "Scripts have compiler errors", False) == "failed"
    assert (
        classify_player_build(1, "No valid Unity Editor license", False) == "infrastructure_error"
    )
    assert classify_player_build(0, "", False, timed_out=True) == "timed_out"

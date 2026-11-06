from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from game_pipeline.codex_cli.config import (
    CodexHarnessSettings,
    _discover_codex_executable,
    resolve_game_builder,
)
from game_pipeline.codex_cli.harness import (
    COMPLETION_SCHEMA,
    _failure_severity,
    _failure_signature,
    _implementation_prompt,
    _permission_diagnostic_failed,
    _prepare_host_owned_source_roots,
    _ProjectSourceSnapshot,
    _repair_is_regression,
    _repair_prompt,
    _validation_progress,
    _write_project_instructions,
    prepare_design_for_codex,
)
from game_pipeline.codex_cli.runner import CodexCliRunner
from game_pipeline.unity_project_validator import UnityValidationOutcome


def _settings(executable: Path) -> CodexHarnessSettings:
    return CodexHarnessSettings(
        executable=executable,
        model="gpt-test",
        reasoning_effort="high",
        invocation_timeout_seconds=60,
        total_timeout_seconds=120,
        max_repairs=2,
    )


def _completion() -> dict[str, object]:
    return {
        "status": "completed",
        "summary": "implemented",
        "changed_files": ["Assets/Game.cs"],
        "implemented_features": ["movement"],
        "tests_run": ["compile"],
        "unresolved_requirements": [],
        "recommended_validation": ["Unity batch mode"],
    }


def test_runner_uses_scoped_workspace_and_does_not_forward_api_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "unity"
    project.mkdir()
    executable = tmp_path / "codex.exe"
    executable.write_bytes(b"")
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        answer = Path(command[command.index("--output-last-message") + 1])
        answer.write_text(json.dumps(_completion()), encoding="utf-8")
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"type": "turn.completed", "usage": {"input_tokens": 10}}) + "\n",
            stderr="",
        )

    monkeypatch.setenv("OPENAI_API_KEY", "must-not-leak")
    monkeypatch.setenv("GEMINI_API_KEY", "must-not-leak")
    with patch("game_pipeline.codex_cli.runner.subprocess.run", side_effect=fake_run):
        result = CodexCliRunner(_settings(executable)).run(
            project_root=project,
            prompt="implement",
            schema=COMPLETION_SCHEMA,
            audit_directory=tmp_path / "audit",
        )

    command = captured["command"]
    assert command[command.index("--cd") + 1] == str(project.resolve())
    assert command[command.index("--sandbox") + 1] == "workspace-write"
    assert "--json" in command
    assert command[command.index("--model") + 1] == "gpt-test"
    assert "model_reasoning_effort=high" in command
    environment = captured["kwargs"]["env"]
    assert "OPENAI_API_KEY" not in environment
    assert "GEMINI_API_KEY" not in environment
    assert result.final_response == _completion()
    assert result.events[0]["type"] == "turn.completed"


def test_runner_rejects_non_jsonl_output(tmp_path: Path) -> None:
    project = tmp_path / "unity"
    project.mkdir()
    executable = tmp_path / "codex.exe"
    executable.write_bytes(b"")
    completed = subprocess.CompletedProcess([], 0, stdout="not-json\n", stderr="")
    with (
        patch("game_pipeline.codex_cli.runner.subprocess.run", return_value=completed),
        pytest.raises(RuntimeError, match="stdout was not JSONL"),
    ):
        CodexCliRunner(_settings(executable)).run(
            project_root=project,
            prompt="implement",
            schema=COMPLETION_SCHEMA,
            audit_directory=tmp_path / "audit",
        )


def test_prepare_design_routes_only_missing_mechanics_to_codex() -> None:
    design = {
        "unsupported_mechanics": ["wall_climb", "air_dash"],
        "generated_modules": [{"module_id": "old"}],
    }
    result = prepare_design_for_codex(design)  # type: ignore[arg-type]
    assert result["codex_harness_requirements"] == ["wall_climb", "air_dash"]
    assert result["unsupported_mechanics"] == []
    assert result["generated_modules"] == []


def test_game_builder_aliases(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAINFLOW_GAME_BUILDER", "codex-cli")
    assert resolve_game_builder() == "codex_cli"
    monkeypatch.setenv("MAINFLOW_GAME_BUILDER", "claude-code")
    assert resolve_game_builder() == "claude_code"
    monkeypatch.setenv("MAINFLOW_GAME_BUILDER", "unknown")
    with pytest.raises(ValueError, match="MAINFLOW_GAME_BUILDER"):
        resolve_game_builder()


def test_codex_defaults_to_luna_medium(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    executable = tmp_path / "codex.exe"
    executable.write_bytes(b"")
    monkeypatch.setenv("MAINFLOW_CODEX_CLI_PATH", str(executable))
    monkeypatch.delenv("MAINFLOW_CODEX_MODEL", raising=False)
    monkeypatch.delenv("MAINFLOW_CODEX_REASONING_EFFORT", raising=False)

    settings = CodexHarnessSettings.from_environment()

    assert settings.model == "gpt-5.6-luna"
    assert settings.reasoning_effort == "medium"


def test_prepares_generated_source_roots_before_codex(tmp_path: Path) -> None:
    project = tmp_path / "unity"
    project.mkdir()

    _prepare_host_owned_source_roots(project)

    assert (project / "Assets/GameTemplate/Generated/Scripts").is_dir()
    assert (project / "Assets/GameTemplate/Generated/Validation").is_dir()


def test_permission_diagnostic_detects_access_denied_even_with_zero_exit() -> None:
    assert _permission_diagnostic_failed("file.cs: Access is denied.")
    assert not _permission_diagnostic_failed("Successfully processed 12 files")
    assert not _permission_diagnostic_failed(
        "Successfully processed 236 files; Failed processing 0 files"
    )
    assert _permission_diagnostic_failed(
        "Successfully processed 235 files; Failed processing 1 files"
    )


def test_discovers_stable_codex_desktop_shim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    desktop_shim = tmp_path / "OpenAI" / "Codex" / "bin" / "codex.exe"
    desktop_shim.parent.mkdir(parents=True)
    desktop_shim.write_bytes(b"")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr("game_pipeline.codex_cli.config.shutil.which", lambda _name: None)

    assert _discover_codex_executable() == str(desktop_shim)


def test_prefers_newest_versioned_codex_desktop_binary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    older = tmp_path / "OpenAI" / "Codex" / "bin" / "old" / "codex.exe"
    newer = tmp_path / "OpenAI" / "Codex" / "bin" / "new" / "codex.exe"
    older.parent.mkdir(parents=True)
    newer.parent.mkdir(parents=True)
    older.write_bytes(b"old")
    newer.write_bytes(b"new")
    older.touch()
    newer.touch()
    older_stat = older.stat()
    os.utime(older, ns=(older_stat.st_atime_ns, older_stat.st_mtime_ns - 1_000_000))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr("game_pipeline.codex_cli.config.shutil.which", lambda _name: None)

    assert _discover_codex_executable() == str(newer)


def test_codex_prompts_reserve_unity_process_ownership_for_host(tmp_path: Path) -> None:
    project = tmp_path / "unity"
    project.mkdir()
    design = {
        "codex_harness_requirements": ["wall_climb"],
    }
    request = {
        "condition": "벽을 타는 게임",
        "genre": "플랫포머",
        "viewpoint": "사이드뷰",
    }

    _write_project_instructions(project, design, request)  # type: ignore[arg-type]
    instructions = (project / "AGENTS.md").read_text(encoding="utf-8")
    implementation = _implementation_prompt(design, request)  # type: ignore[arg-type]
    repair = _repair_prompt({"issues": []}, 1)

    assert "Do not launch Unity Editor" in instructions
    assert "Never create, edit, delete, or invent Unity `.meta` files" in instructions
    assert "every public `MonoBehaviour`" in instructions
    assert "Do not launch" in implementation and "Unity" in implementation
    assert "Do not launch Unity Editor" in repair


def test_runtime_failure_signature_uses_actual_failed_transition() -> None:
    collectible = UnityValidationOutcome(
        checks=[
            {
                "criterion_id": "unity.runtime_smoke",
                "passed": False,
                "message": "Play Mode smoke tests failed; inspect log",
            }
        ],
        issues=[
            {
                "code": "UNITY_RUNTIME_TEST_FAILED",
                "severity": "error",
                "message": "Play Mode smoke tests failed; inspect log",
            }
        ],
        unity_log=(
            'UNITY_PLAYTEST_METRICS:{"failed_transition":"runtime.collectible_trigger"}\n'
            "UNITY_RUNTIME_SMOKE_FAILED: runtime.collectible_trigger: count did not increase"
        ),
    )
    missing_module = UnityValidationOutcome(
        checks=collectible.checks,
        issues=collectible.issues,
        unity_log=(
            'UNITY_PLAYTEST_METRICS:{"failed_transition":"runtime.missing_module"}\n'
            "VALIDATION_FAIL:template.missing_module:generated_feature_05"
        ),
    )

    assert _failure_signature(collectible) != _failure_signature(missing_module)
    assert _failure_severity(missing_module) > _failure_severity(collectible)


def test_batch_exception_is_more_severe_than_missing_module() -> None:
    missing_module = UnityValidationOutcome(
        checks=[],
        issues=[{"code": "FAILED", "severity": "error", "message": "missing_module"}],
        unity_log="VALIDATION_FAIL:template.missing_module:generated_feature_05",
    )
    batch_exception = UnityValidationOutcome(
        checks=[],
        issues=[{"code": "FAILED", "severity": "error", "message": "batch failed"}],
        unity_log=(
            "FileNotFoundException: Could not load the file 'TeamIdle.GameTemplate.Generated'.\n"
            "executeMethod class 'TemplateProjectBuilder' threw exception."
        ),
    )

    assert _failure_severity(batch_exception) > _failure_severity(missing_module)
    signature = _failure_signature(batch_exception)
    assert "FileNotFoundException" in signature


def test_downstream_validation_failure_preserves_compile_fix() -> None:
    compiler_failure = UnityValidationOutcome(
        checks=[],
        issues=[{"code": "FAILED", "severity": "error", "message": "compiler"}],
        unity_log=(
            "Scripts have compiler errors.\n"
            "GeneratedFeature02Module.cs(9,25): error CS0534: missing OnInitialize"
        ),
    )
    downstream_failure = UnityValidationOutcome(
        checks=[],
        issues=[{"code": "FAILED", "severity": "error", "message": "validation plan"}],
        unity_log=(
            "UNITY_MODULE_CATALOG_OK:20\n"
            "InvalidOperationException: Validation plan is invalid or incomplete.\n"
            "TemplateProjectBuilder threw exception."
        ),
    )

    assert _failure_severity(downstream_failure) > _failure_severity(compiler_failure)
    assert _validation_progress(downstream_failure) > _validation_progress(compiler_failure)
    assert not _repair_is_regression(compiler_failure, downstream_failure)


def test_repair_that_loses_a_validation_milestone_is_rolled_back() -> None:
    baseline = UnityValidationOutcome(
        checks=[],
        issues=[{"code": "FAILED", "severity": "error", "message": "scene"}],
        unity_log="UNITY_MODULE_CATALOG_OK:4\nUNITY_GENERATED_FEATURE_BINDINGS_OK:2",
    )
    candidate = UnityValidationOutcome(
        checks=[],
        issues=[{"code": "FAILED", "severity": "error", "message": "compiler"}],
        unity_log="Scripts have compiler errors.\nFeature.cs(1,1): error CS1002",
    )

    assert _repair_is_regression(baseline, candidate)


def test_source_snapshot_restores_changed_and_deleted_files(tmp_path: Path) -> None:
    project = tmp_path / "unity"
    source = project / "Assets" / "Feature.cs"
    source.parent.mkdir(parents=True)
    source.write_text("original", encoding="utf-8")
    snapshot = _ProjectSourceSnapshot.capture(project)

    source.write_text("regressed", encoding="utf-8")
    added = project / "Assets" / "Broken.meta"
    added.write_text("invented", encoding="utf-8")
    snapshot.restore(project)

    assert source.read_text(encoding="utf-8") == "original"
    assert not added.exists()

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from game_pipeline.codex_cli.config import (
    CodexHarnessSettings,
    _discover_codex_executable,
    resolve_game_builder,
)
from game_pipeline.codex_cli.harness import (
    COMPLETION_SCHEMA,
    CodexGameHarness,
    _failure_severity,
    _failure_signature,
    _implementation_prompt,
    _permission_diagnostic_failed,
    _prepare_host_owned_source_roots,
    _ProjectSourceSnapshot,
    _repair_is_regression,
    _repair_prompt,
    _require_agent_completion,
    _restore_protected_asset_files,
    _validation_progress,
    _write_project_instructions,
    prepare_design_for_codex,
)
from game_pipeline.codex_cli.preflight import CodexPreflightResult
from game_pipeline.codex_cli.runner import (
    CodexCliResult,
    CodexCliRunner,
    _AgentProgressReporter,
    _stream_codex_process,
)
from game_pipeline.implementation_task_planner import build_implementation_tasks
from game_pipeline.unity_project_validator import UnityValidationOutcome


def _settings(executable: Path) -> CodexHarnessSettings:
    return CodexHarnessSettings(
        executable=executable,
        model="gpt-test",
        reasoning_effort="high",
        invocation_timeout_seconds=60,
        total_timeout_seconds=120,
        max_repairs=2,
        service_tier="fast",
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


@pytest.mark.parametrize("unity_status", ["passed", "failed"])
def test_quality_repair_keeps_only_unity_validated_source(
    tmp_path: Path, unity_status: str
) -> None:
    project = tmp_path / "unity"
    source = project / "Assets/Game.cs"
    asset = project / "Assets/GameTemplate/Generated/AppliedAssets/tower.png"
    source.parent.mkdir(parents=True)
    asset.parent.mkdir(parents=True)
    source.write_text("original", encoding="utf-8")
    asset.write_bytes(b"validated-image")
    runner = MagicMock()

    def edit_project(**kwargs):
        source.write_text("repaired", encoding="utf-8")
        asset.write_bytes(b"unvalidated-replacement")
        return MagicMock(final_response=_completion())

    runner.run.side_effect = edit_project
    harness = CodexGameHarness(
        _settings(tmp_path / "codex.exe"),
        audit_root=tmp_path / "audit",
        runner=runner,
        preflight_runner=lambda settings: CodexPreflightResult("codex", "test", "logged in"),
    )
    issues = (
        [{"code": "UNITY_RUNTIME_TEST_FAILED", "severity": "error", "message": "test"}]
        if unity_status == "failed"
        else []
    )
    outcome = UnityValidationOutcome(checks=[], issues=issues, unity_log="test")
    with (
        patch(
            "game_pipeline.codex_cli.harness._normalize_windows_project_permissions",
            return_value={"status": "normalized"},
        ),
        patch("game_pipeline.codex_cli.harness.UnityProjectValidator") as validator,
    ):
        validator.return_value.validate.return_value = outcome
        if unity_status == "passed":
            assert (
                harness.repair_quality_findings(
                    project_root=project,
                    draft={"status": "generated"},
                    request={"condition": "defend the base"},
                    findings=[{"severity": "error", "message": "cannon splash missing"}],
                    iteration=1,
                ).status
                == "passed"
            )
        else:
            with pytest.raises(RuntimeError, match="Unity validation failed|same Unity failure"):
                harness.repair_quality_findings(
                    project_root=project,
                    draft={"status": "generated"},
                    request={"condition": "defend the base"},
                    findings=[{"severity": "error", "message": "cannon splash missing"}],
                    iteration=1,
                )

    assert source.read_text(encoding="utf-8") == (
        "repaired" if unity_status == "passed" else "original"
    )
    assert asset.read_bytes() == b"validated-image"
    assert runner.run.call_count == (1 if unity_status == "passed" else 3)


def test_runner_uses_scoped_workspace_and_does_not_forward_api_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "unity"
    project.mkdir()
    executable = tmp_path / "codex.exe"
    executable.write_bytes(b"")
    captured: dict[str, object] = {}

    def fake_run(**kwargs):
        command = kwargs["command"]
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
    with patch("game_pipeline.codex_cli.runner._stream_codex_process", side_effect=fake_run):
        result = CodexCliRunner(_settings(executable)).run(
            project_root=project,
            prompt="implement",
            schema=COMPLETION_SCHEMA,
            audit_directory=tmp_path / "audit",
        )

    command = captured["command"]
    assert command[command.index("--cd") + 1] == str(project.resolve())
    assert command[command.index("--sandbox") + 1] == "workspace-write"
    assert "--skip-git-repo-check" in command
    assert "--json" in command
    assert command[command.index("--model") + 1] == "gpt-test"
    assert "model_reasoning_effort=high" in command
    assert 'service_tier="fast"' in command
    environment = captured["kwargs"]["environment"]
    assert "OPENAI_API_KEY" not in environment
    assert "GEMINI_API_KEY" not in environment
    assert result.final_response == _completion()
    assert result.events[0]["type"] == "turn.completed"


def test_runner_bypasses_nested_sandbox_only_when_docker_flag_is_enabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "unity"
    project.mkdir()
    executable = tmp_path / "codex"
    executable.write_bytes(b"")
    captured: dict[str, object] = {}

    def fake_run(**kwargs):
        command = kwargs["command"]
        captured["command"] = command
        answer = Path(command[command.index("--output-last-message") + 1])
        answer.write_text(json.dumps(_completion()), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout='{"type":"turn.completed"}\n')

    monkeypatch.setenv("MAINFLOW_CODEX_DOCKER_BYPASS_SANDBOX", "1")
    with patch("game_pipeline.codex_cli.runner._stream_codex_process", side_effect=fake_run):
        CodexCliRunner(_settings(executable)).run(
            project_root=project,
            prompt="implement",
            schema=COMPLETION_SCHEMA,
            audit_directory=tmp_path / "audit",
        )

    command = captured["command"]
    assert "--dangerously-bypass-approvals-and-sandbox" in command
    assert "--sandbox" not in command


def test_needs_attention_agent_result_is_not_accepted_as_implementation(tmp_path: Path) -> None:
    result = CodexCliResult(
        exit_code=0,
        elapsed_seconds=1.0,
        final_response={
            "status": "needs_attention",
            "summary": "bwrap could not create a namespace",
            "changed_files": [],
            "implemented_features": [],
            "tests_run": [],
            "unresolved_requirements": ["project files could not be inspected"],
            "recommended_validation": [],
        },
        events=(),
        audit_directory=tmp_path,
    )

    with pytest.raises(RuntimeError, match="AGENT_IMPLEMENTATION_INCOMPLETE.*bwrap"):
        _require_agent_completion(result, "initial implementation")


def test_runner_rejects_non_jsonl_output(tmp_path: Path) -> None:
    project = tmp_path / "unity"
    project.mkdir()
    executable = tmp_path / "codex.exe"
    executable.write_bytes(b"")
    completed = subprocess.CompletedProcess([], 0, stdout="not-json\n", stderr="")
    with (
        patch("game_pipeline.codex_cli.runner._stream_codex_process", return_value=completed),
        pytest.raises(RuntimeError, match="stdout was not JSONL"),
    ):
        CodexCliRunner(_settings(executable)).run(
            project_root=project,
            prompt="implement",
            schema=COMPLETION_SCHEMA,
            audit_directory=tmp_path / "audit",
        )


def test_streaming_runner_emits_curated_progress_and_keeps_jsonl(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    script = (
        "import json,sys; sys.stdin.read(); "
        "print(json.dumps({'type':'turn.started'}), flush=True); "
        "print(json.dumps({'type':'item.completed','item':{'type':'file_change'}}), flush=True); "
        "print(json.dumps({'type':'turn.completed'}), flush=True)"
    )
    events_path = tmp_path / "events.jsonl"
    stderr_path = tmp_path / "stderr.log"

    result = _stream_codex_process(
        command=[sys.executable, "-c", script],
        prompt="implement",
        cwd=tmp_path,
        environment=dict(os.environ),
        timeout_seconds=10,
        events_path=events_path,
        stderr_path=stderr_path,
    )

    output = capsys.readouterr().out
    assert result.returncode == 0
    assert "[AGENT][context]" in output
    assert "[AGENT][edit]" in output
    assert "[AGENT][finalize]" in output
    assert len(events_path.read_text(encoding="utf-8").splitlines()) == 3


def test_streaming_runner_enforces_timeout_after_stdout_closes(tmp_path: Path) -> None:
    events_path = tmp_path / "events.jsonl"
    stderr_path = tmp_path / "stderr.log"
    script = "import sys,time; sys.stdout.close(); time.sleep(3)"
    started = time.monotonic()

    with pytest.raises(TimeoutError, match="CODEX_PROCESS_TIMEOUT"):
        _stream_codex_process(
            command=[sys.executable, "-c", script],
            prompt="implement",
            cwd=tmp_path,
            environment=dict(os.environ),
            timeout_seconds=1,
            events_path=events_path,
            stderr_path=stderr_path,
        )

    assert time.monotonic() - started < 2.5


def test_progress_reporter_does_not_treat_unity_paths_as_validation(
    capsys: pytest.CaptureFixture[str],
) -> None:
    reporter = _AgentProgressReporter()
    reporter.emit("context", "start")
    reporter.observe(
        {
            "type": "item.completed",
            "item": {
                "type": "command_execution",
                "command": "rg -n Goal Assets/GameTemplate/Runtime/UnityProject.cs",
            },
        }
    )
    reporter.observe(
        {
            "type": "item.completed",
            "item": {
                "type": "command_execution",
                "command": "apply_patch tests/UnityRuntimeTests.cs",
            },
        }
    )

    output = capsys.readouterr().out
    assert "[AGENT][edit]" in output
    assert "[AGENT][validate]" not in output


def test_prepare_design_gives_harness_all_gameplay_mechanics() -> None:
    design = {
        "common_modules": ["game_bootstrap", "input_adapter"],
        "selected_modules": [
            "game_bootstrap",
            "input_adapter",
            "platformer_movement",
            "goal_system",
        ],
        "unsupported_mechanics": ["wall_climb", "air_dash"],
        "generated_modules": [{"module_id": "old"}],
        "game_spec": {
            "features": [
                {
                    "feature_id": "climb_goal",
                    "description": "벽을 타고 목표에 도달한다.",
                    "required": True,
                }
            ]
        },
    }
    result = prepare_design_for_codex(design)  # type: ignore[arg-type]
    assert result["codex_harness_requirements"] == [
        "platformer_movement",
        "goal_system",
        "wall_climb",
        "air_dash",
    ]
    assert result["agent_harness_template_modules"] == [
        "platformer_movement",
        "goal_system",
    ]
    assert result["agent_harness_feature_requirements"][0]["feature_id"] == "climb_goal"
    assert result["agent_harness_mode"] == "whole_project"
    assert result["unsupported_mechanics"] == []
    assert result["generated_modules"] == []


def test_agent_harness_task_plan_does_not_preapprove_template_modules() -> None:
    design = {
        "agent_harness_mode": "whole_project",
        "codex_harness_requirements": ["platformer_movement", "goal_system"],
        "game_spec": {"genre": "Platformer"},
    }

    plan = build_implementation_tasks(design, time_budget_seconds=7200)  # type: ignore[arg-type]
    task_ids = [task["task_id"] for task in plan["tasks"]]

    assert task_ids == [
        "design-review",
        "unity-project-generation",
        "project-context-review",
        "unity-playmode-validation",
        "quality-evaluation",
        "package-project",
    ]
    assert not any(task_id.startswith("bind-module-") for task_id in task_ids)


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
    monkeypatch.delenv("MAINFLOW_CODEX_SERVICE_TIER", raising=False)

    settings = CodexHarnessSettings.from_environment()

    assert settings.model == "gpt-5.6-luna"
    assert settings.reasoning_effort == "medium"
    assert settings.service_tier is None


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
    assert "compatibility scaffold, not a finished genre template" in instructions
    assert "reference implementations only" in instructions
    assert "Never create, edit, delete, or invent Unity `.meta` files" in instructions
    assert "every public `MonoBehaviour`" in instructions
    assert "Every concrete generated module class must itself be `public`" in instructions
    assert "presentation_plan.json` as an implementation contract" in instructions
    assert "PrototypeSceneController` IMGUI debug panel" in instructions
    assert "1280x720 and 1920x1080" in instructions
    assert "sound_asset_request.json" in instructions
    assert "generation_spec.audio_cue" in instructions
    assert "before -> after" in instructions
    assert "Do not launch" in implementation and "Unity" in implementation
    assert "substantially the same game" in implementation
    assert "Do not launch Unity Editor" in repair


def test_downstream_validation_failure_is_repaired_and_revalidated(tmp_path: Path) -> None:
    project = tmp_path / "unity"
    (project / "Assets").mkdir(parents=True)
    executable = tmp_path / "codex.exe"
    executable.write_bytes(b"")
    prompts: list[str] = []

    class FakeRunner:
        def run(self, **kwargs):
            prompts.append(kwargs["prompt"])
            return CodexCliResult(
                exit_code=0,
                elapsed_seconds=0.1,
                final_response=_completion(),
                events=(),
                audit_directory=kwargs["audit_directory"],
            )

    failed = UnityValidationOutcome(
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
        unity_log="UNITY_RUNTIME_SMOKE_FAILED: runtime.hazard_damage",
    )
    passed = UnityValidationOutcome(
        checks=[
            {
                "criterion_id": "unity.runtime_smoke",
                "passed": True,
                "message": "Play Mode smoke tests passed",
            }
        ],
        unity_log="UNITY_RUNTIME_SMOKE_OK:passed",
    )
    harness = CodexGameHarness(
        _settings(executable),
        audit_root=tmp_path / "audit",
        runner=FakeRunner(),
        preflight_runner=lambda _settings: CodexPreflightResult(
            str(executable), "codex-test", "logged in"
        ),
    )
    draft = {
        "contract_version": "3.0.0",
        "draft_id": "test",
        "status": "generated",
        "engine": "Unity",
        "entry_scene": "game/unity_project/Assets/Scenes/Bootstrap.unity",
        "source_artifacts": [],
        "required_image_asset_ids": [],
        "required_sound_asset_ids": [],
        "notes": [],
    }
    request = {
        "contract_version": "3.0.0",
        "image_style": "Pixel Art",
        "mood_style": "Fantasy",
        "genre": "플랫포머",
        "viewpoint": "사이드뷰",
        "condition": "함정 피해를 받는 게임",
        "custom_image": None,
    }

    with (
        patch(
            "game_pipeline.codex_cli.harness._normalize_windows_project_permissions",
            return_value={"status": "passed"},
        ),
        patch("game_pipeline.codex_cli.harness._require_normalized_permissions"),
        patch(
            "game_pipeline.codex_cli.harness.UnityProjectValidator.validate",
            return_value=passed,
        ),
    ):
        result = harness.repair_existing_project(
            project_root=project,
            draft=draft,  # type: ignore[arg-type]
            request=request,  # type: ignore[arg-type]
            initial_outcome=failed,
            phase="final_validation",
            max_repairs=2,
        )

    assert result.outcome.status == "passed"
    assert len(result.repair_results) == 1
    assert result.validation_attempts[0]["phase"] == "final_validation"
    assert "Validation phase: final_validation" in prompts[0]
    assert "preserve generated and applied image/audio" in prompts[0]


def test_final_repair_restores_validated_assets_but_keeps_source_changes(tmp_path: Path) -> None:
    project = tmp_path / "unity"
    asset = project / "Assets/GameTemplate/Generated/AppliedAssets/player.png"
    manifest = project / "Assets/GameTemplate/Generated/AssetBindingManifest.json"
    source = project / "Assets/GameTemplate/Runtime/Game.cs"
    for path, content in (
        (asset, b"validated-image"),
        (manifest, b'{"validated":true}'),
        (source, b"old-source"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    snapshot = _ProjectSourceSnapshot.capture(project)
    asset.write_bytes(b"agent-replaced-image")
    manifest.write_bytes(b"{}")
    extra = project / "Assets/GameTemplate/Generated/AppliedAssets/unapproved.png"
    extra.write_bytes(b"new")
    source.write_bytes(b"repaired-source")

    restored = _restore_protected_asset_files(snapshot, project)

    assert asset.read_bytes() == b"validated-image"
    assert manifest.read_bytes() == b'{"validated":true}'
    assert not extra.exists()
    assert source.read_bytes() == b"repaired-source"
    assert len(restored) == 3


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

from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path
from typing import cast
from unittest.mock import Mock, patch

import pytest

from mainflow.ArtifactManager import ArtifactManager
from mainflow.contracts import LogicAnalysis, WorkflowState
from mainflow.nodes import analysis_node, logic_analysis_node, parse_input_node, user_input_node
from mainflow.preview_features import main as preview_main

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
LOCAL_WEB_ROOT = REPOSITORY_ROOT / "CI" / "CD" / "LocalWeb"


def _load_service_module():
    sys.path.insert(0, str(LOCAL_WEB_ROOT))
    spec = importlib.util.spec_from_file_location(
        "mainflow_local_web_service",
        LOCAL_WEB_ROOT / "service.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _request_payload() -> dict[str, str]:
    return {
        "image_style": "Pixel Art",
        "mood_style": "Fantasy",
        "genre": "플랫포머",
        "viewpoint": "사이드뷰",
        "condition": "플레이어가 좌우로 이동하고 점프한 뒤 목적지에 도달한다.",
    }


def test_web_ui_exposes_completion_notifications() -> None:
    html = (LOCAL_WEB_ROOT / "static" / "index.html").read_text(encoding="utf-8")
    script = (LOCAL_WEB_ROOT / "static" / "app.js").read_text(encoding="utf-8")

    assert 'id="completion-notifications"' in html
    assert "Notification.requestPermission()" in script
    assert 'notifyJobMilestone(job, "feature")' in script
    assert 'notifyJobMilestone(job, "terminal")' in script
    assert "playNotificationTone" in script


def test_web_ui_downloads_host_unity_launcher_for_docker() -> None:
    script = (LOCAL_WEB_ROOT / "static" / "app.js").read_text(encoding="utf-8")

    assert 'result.status === "launcher_required"' in script
    assert "result.launcher_url" in script
    assert "다운로드된 .cmd 파일을 실행하세요" in script


def test_web_ui_exposes_provider_specific_harness_settings() -> None:
    html = (LOCAL_WEB_ROOT / "static" / "index.html").read_text(encoding="utf-8")
    script = (LOCAL_WEB_ROOT / "static" / "app.js").read_text(encoding="utf-8")

    assert 'id="agent-harness-settings"' in html
    assert 'name="agent_model"' in html
    assert 'name="agent_reasoning_effort"' in html
    assert 'name="agent_fast_mode"' in html
    for model in (
        "default",
        "gpt-6.1-sol",
        "gpt-6-astra",
        "gpt-6.1-terra",
        "gpt-6-sol",
        "gpt-6-luna",
        "gpt-5.6-sol",
        "gpt-5.6-terra",
        "gpt-5.6-luna",
    ):
        assert f'["{model}",' in script
    assert '["sonnet", "Claude Sonnet · 균형형"]' in script
    assert 'defaultModel: "gpt-5.6-luna"' in script
    assert "updateAgentHarnessSettings" in script


def test_web_ui_allows_optional_reference_image_for_every_style() -> None:
    html = (LOCAL_WEB_ROOT / "static" / "index.html").read_text(encoding="utf-8")
    script = (LOCAL_WEB_ROOT / "static" / "app.js").read_text(encoding="utf-8")

    custom_input = html.split('id="custom-image"', maxsplit=1)[1].split(">", maxsplit=1)[0]
    assert "disabled" not in custom_input
    assert "customImage.required = customSelected" in script
    assert 'customImage.value = ""' not in script


def test_web_ui_formats_fastapi_validation_errors() -> None:
    script = (LOCAL_WEB_ROOT / "static" / "app.js").read_text(encoding="utf-8")

    assert "function formatApiError(payload, status)" in script
    assert 'item.loc.filter((part) => part !== "body").join(".")' in script
    assert 'messages.join("\\n")' in script
    assert "new Error(formatApiError(payload, response.status))" in script


def test_settings_store_never_returns_api_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    service = _load_service_module()
    state_root = tmp_path / ".localweb"
    monkeypatch.setattr(service, "LOCAL_WEB_STATE_ROOT", state_root)
    monkeypatch.setattr(service, "SETTINGS_PATH", state_root / "settings.json")
    monkeypatch.setattr(service, "SECRETS_PATH", state_root / "secrets.env")

    store = service.LocalWebSettingsStore()
    roles = store.load_roles()
    roles["condition_feature_analysis"] = service.RoleSelection(
        provider="openai",
        model="gpt-6.1-sol",
    )
    store.save(
        service.ModelSettingsUpdate(
            roles=roles,
            api_keys={"openai": "test-secret-key"},
        )
    )

    public_payload = store.public_catalog()
    assert public_payload["api_keys"]["openai"] == {"configured": True}
    assert "test-secret-key" not in json.dumps(public_payload)
    assert store.process_environment()["OPENAI_API_KEY"] == "test-secret-key"
    assert "test-secret-key" not in (state_root / "settings.json").read_text(encoding="utf-8")


def test_preview_and_confirmed_logic_use_identical_features(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    workspace = tmp_path / "workspace"
    request_file = tmp_path / "request.json"
    output_file = tmp_path / "preview.json"
    request_file.write_text(
        json.dumps(_request_payload(), ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setenv("MAINFLOW_CONDITION_FEATURE_PROVIDER", "off")
    monkeypatch.setenv("MAINFLOW_GENRE_FEATURE_PROVIDER", "off")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "preview_features",
            "--request-file",
            str(request_file),
            "--workspace",
            str(workspace),
            "--output-file",
            str(output_file),
        ],
    )

    assert preview_main() == 0
    preview = json.loads(output_file.read_text(encoding="utf-8"))
    approved_logic = json.loads(Path(preview["logic_analysis_path"]).read_text(encoding="utf-8"))

    monkeypatch.setenv("MAINFLOW_WORKSPACE", str(workspace))
    monkeypatch.setenv("MAINFLOW_APPROVED_LOGIC_ANALYSIS", preview["logic_analysis_path"])
    state = cast(WorkflowState, dict(_request_payload()))
    for node in (user_input_node, parse_input_node, analysis_node, logic_analysis_node):
        state.update(node(state))
    actual = cast(LogicAnalysis, ArtifactManager().read_json(state["logic_analysis"]))

    assert actual["features"] == approved_logic["features"]
    condition_report = ArtifactManager().read_project_file(
        state["project_id"],
        "data/condition_feature_analysis.json",
    )
    assert json.loads(condition_report)["status"] == "approved_preview"


def test_generation_request_rejects_custom_style_without_file():
    service = _load_service_module()
    with pytest.raises(ValueError, match="Custom image style"):
        service.GenerationRequest(
            mode="generate",
            image_style="Custom",
            mood_style="Fantasy",
            genre="플랫포머",
            viewpoint="사이드뷰",
            condition="점프 게임",
        )


def test_generation_request_accepts_codex_cli_builder():
    service = _load_service_module()
    request = service.GenerationRequest(
        mode="generate",
        game_builder="codex_cli",
        agent_model="gpt-6.1-sol",
        agent_reasoning_effort="high",
        agent_fast_mode=True,
        **_request_payload(),
    )
    assert request.game_builder == "codex_cli"
    assert request.agent_model == "gpt-6.1-sol"
    assert request.agent_reasoning_effort == "high"
    assert request.agent_fast_mode is True


def test_generation_request_accepts_claude_code_builder():
    service = _load_service_module()
    request = service.GenerationRequest(
        mode="generate",
        game_builder="claude_code",
        agent_model="opus",
        agent_reasoning_effort="xhigh",
        **_request_payload(),
    )
    assert request.game_builder == "claude_code"
    assert request.agent_model == "opus"
    assert request.agent_reasoning_effort == "xhigh"


def test_generation_request_rejects_fast_mode_for_claude_code():
    service = _load_service_module()
    with pytest.raises(ValueError, match="Fast mode is only supported"):
        service.GenerationRequest(
            mode="generate",
            game_builder="claude_code",
            agent_fast_mode=True,
            **_request_payload(),
        )


def test_generation_request_rejects_explicit_conflicting_genre():
    service = _load_service_module()
    with pytest.raises(ValueError, match="장르 '뱀서류'.*'플랫포머'"):
        service.GenerationRequest(
            mode="generate",
            game_builder="codex_cli",
            image_style="Pixel Art",
            mood_style="Fantasy",
            genre="뱀서류",
            viewpoint="사이드뷰",
            condition="붕괴하는 탑을 탈출하는 액션 플랫포머 게임",
        )


def test_recovers_project_id_from_failed_workflow_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    service = _load_service_module()
    workspace = tmp_path / "workspace"
    project = workspace / "20261105_77" / "game" / "unity_project"
    (project / "ProjectSettings").mkdir(parents=True)
    (project / "ProjectSettings" / "ProjectVersion.txt").write_text(
        "m_EditorVersion: 6000.0.71f1\n", encoding="utf-8"
    )
    report = tmp_path / "unity_project_path.txt"
    report.write_text(str(project), encoding="utf-8")
    monkeypatch.setattr(service, "WORKSPACE_ROOT", workspace.resolve())

    assert service._project_id_from_unity_report(report) == "20261105_77"


def test_docker_mountinfo_resolves_windows_workspace_path() -> None:
    service = _load_service_module()
    mountinfo = (
        "486 476 0:68 /Users/leedo/Documents/CapstonDesignII/feat-WebManage/workspace "
        "/app/workspace rw,noatime - 9p C:\\134 rw,aname=drvfs;path=C:\\;uid=0"
    )

    result = service._host_workspace_from_mountinfo(mountinfo, Path("/app/workspace"))

    assert str(result) == (r"C:\Users\leedo\Documents\CapstonDesignII\feat-WebManage\workspace")


def test_windows_unity_launcher_targets_host_project() -> None:
    service = _load_service_module()

    launcher = service._windows_unity_launcher(
        service.PureWindowsPath(
            r"C:\Users\leedo\Documents\CapstonDesignII\feat-WebManage\workspace\20261114_02\game\unity_project"
        ),
        "6000.0.71f1",
    )

    assert "6000.0.71f1\\Editor\\Unity.exe" in launcher
    assert "workspace\\20261114_02\\game\\unity_project" in launcher
    assert 'start "" "%MAINFLOW_UNITY%" -projectPath "%MAINFLOW_PROJECT%"' in launcher


def test_cancel_stops_running_process_tree_and_preserves_cancelled_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    service = _load_service_module()
    job_root = tmp_path / "job"
    job_root.mkdir()
    request_file = job_root / "request.json"
    request_file.write_text("{}", encoding="utf-8")
    process = Mock(pid=1234)
    process.poll.return_value = None
    job = service.WorkflowJob(
        job_id="job-id",
        mode="generate",
        request_file=request_file,
        job_root=job_root,
        status="running",
        stage="workflow",
        process=process,
    )
    manager = object.__new__(service.WorkflowJobManager)
    manager.jobs = {job.job_id: job}
    manager.lock = service.threading.RLock()

    with patch.object(service, "_terminate_process_tree") as terminate:
        result = manager.cancel(job.job_id)

    terminate.assert_called_once_with(process)
    assert result.status == "cancelled"
    assert result.stage == "cancelled"
    assert result.cancel_requested is True
    service.WorkflowJobManager._fail(result, "late worker failure")
    assert result.status == "cancelled"


def test_workflow_progress_tracks_agent_and_validation_milestones(tmp_path: Path):
    service = _load_service_module()
    job_root = tmp_path / "job-progress"
    job_root.mkdir()
    request_file = job_root / "request.json"
    request_file.write_text("{}", encoding="utf-8")
    job = service.WorkflowJob(
        job_id="progress-job",
        mode="generate",
        request_file=request_file,
        job_root=job_root,
        status="running",
        stage="workflow",
        progress_percent=18,
    )

    job.append_log("[FLOW] 설치된 Codex CLI가 Unity 프로젝트 전체 문맥을 읽습니다.")
    job.append_log("[AGENT][context] 관련 Unity 소스를 읽고 있습니다.")
    job.append_log("[AGENT][edit] Unity 스크립트를 수정하고 있습니다.")
    job.append_log("[FLOW] Unity 컴파일·Play Mode 검증 후 수정합니다.")
    snapshot = job.snapshot()

    assert snapshot["progress_percent"] == 58
    assert snapshot["progress_label"] == "Unity 컴파일·실행 검증"
    assert snapshot["elapsed_seconds"] >= 0
    assert snapshot["estimated_total_seconds"] >= 1200


def test_webgl_preview_progress_tracks_compile_link_and_publish(tmp_path: Path):
    service = _load_service_module()
    job_root = tmp_path / "preview-progress"
    job_root.mkdir()
    job = service.WorkflowJob(
        job_id="preview-progress-job",
        mode="generate",
        request_file=job_root / "request.json",
        job_root=job_root,
        status="failed",
        preview_status="building",
        preview_progress_percent=3,
        preview_started_at=time.monotonic() - 20,
    )

    job.append_log("WEBGL_PREVIEW_STAGE:script_conversion")
    job.append_log("[42/248] C_WebGL_wasm generated.o")
    job.append_log("emcc -O0 -o build.js")
    snapshot = job.snapshot()

    assert snapshot["preview_progress_percent"] == 78
    assert snapshot["preview_progress_label"] == "WebAssembly 링크"
    assert snapshot["preview_elapsed_seconds"] >= 20
    assert snapshot["preview_estimated_total_seconds"] >= 360


def test_cancel_awaiting_confirmation_does_not_need_process(tmp_path: Path):
    service = _load_service_module()
    job_root = tmp_path / "job"
    job_root.mkdir()
    request_file = job_root / "request.json"
    request_file.write_text("{}", encoding="utf-8")
    job = service.WorkflowJob(
        job_id="job-id",
        mode="generate",
        request_file=request_file,
        job_root=job_root,
        status="awaiting_confirmation",
        stage="feature_confirmation",
    )
    manager = object.__new__(service.WorkflowJobManager)
    manager.jobs = {job.job_id: job}
    manager.lock = service.threading.RLock()

    assert manager.cancel(job.job_id).status == "cancelled"


def test_cancel_webgl_preview_preserves_completed_game_state(tmp_path: Path):
    service = _load_service_module()
    job_root = tmp_path / "job"
    job_root.mkdir()
    request_file = job_root / "request.json"
    request_file.write_text("{}", encoding="utf-8")
    process = Mock(pid=1234)
    process.poll.return_value = None
    job = service.WorkflowJob(
        job_id="job-id",
        mode="generate",
        request_file=request_file,
        job_root=job_root,
        status="completed",
        stage="completed",
        project_id="20261109_03",
        preview_status="building",
        process=process,
    )
    manager = object.__new__(service.WorkflowJobManager)
    manager.jobs = {job.job_id: job}
    manager.lock = service.threading.RLock()

    with patch.object(service, "_terminate_process_tree") as terminate:
        result = manager.cancel(job.job_id)

    terminate.assert_called_once_with(process)
    assert result.status == "completed"
    assert result.preview_status == "cancelled"
    assert result.preview_cancel_requested is True


def test_failed_job_can_start_diagnostic_webgl_preview(tmp_path: Path):
    service = _load_service_module()
    job_root = tmp_path / "job"
    job_root.mkdir()
    request_file = job_root / "request.json"
    request_file.write_text("{}", encoding="utf-8")
    job = service.WorkflowJob(
        job_id="job-id",
        mode="generate",
        request_file=request_file,
        job_root=job_root,
        status="failed",
        stage="failed",
        project_id="20261109_08",
        error="runtime validation failed",
    )
    manager = object.__new__(service.WorkflowJobManager)
    manager.jobs = {job.job_id: job}
    manager.lock = service.threading.RLock()
    thread = Mock()

    with patch.object(service.threading, "Thread", return_value=thread):
        result = manager.build_webgl(job.job_id)

    thread.start.assert_called_once_with()
    assert result.status == "failed"
    assert result.preview_status == "building"
    assert result.error == "runtime validation failed"
    assert "진단용 프로젝트" in result.logs[-1]


def test_preview_file_resolution_is_confined_to_webgl_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    service = _load_service_module()
    workspace = tmp_path / "workspace"
    preview = workspace / "20261109_03" / "game" / "webgl"
    preview.mkdir(parents=True)
    index = preview / "index.html"
    index.write_text("preview", encoding="utf-8")
    monkeypatch.setattr(service, "WORKSPACE_ROOT", workspace.resolve())

    assert service.resolve_webgl_preview_file("20261109_03") == index.resolve()
    with pytest.raises(ValueError, match="WebGL 출력 폴더 밖"):
        service.resolve_webgl_preview_file("20261109_03", "../../unity_project/secret.txt")
    with pytest.raises(ValueError, match="프로젝트 ID"):
        service.resolve_webgl_preview_file("../escape")


def test_codex_builder_environment_disables_api_backed_planning():
    service = _load_service_module()
    environment = {
        "MAINFLOW_CONDITION_FEATURE_PROVIDER": "openai",
        "MAINFLOW_DESIGN_V2_PROVIDER": "local",
    }
    service._configure_game_builder_environment(
        environment,
        "codex_cli",
        model="gpt-6.1-sol",
        reasoning_effort="high",
        fast_mode=True,
    )
    assert environment["MAINFLOW_GAME_BUILDER"] == "codex_cli"
    assert environment["MAINFLOW_CONDITION_FEATURE_PROVIDER"] == "off"
    assert environment["MAINFLOW_GENRE_FEATURE_PROVIDER"] == "off"
    assert environment["MAINFLOW_DESIGN_V2_PROVIDER"] == "deterministic"
    assert environment["MAINFLOW_BLUEPRINT_PROVIDER"] == "deterministic"
    assert environment["MAINFLOW_CODEX_STATIC_CHECKLISTS"] == "1"
    assert environment["MAINFLOW_CODEX_MODEL"] == "gpt-6.1-sol"
    assert environment["MAINFLOW_CODEX_REASONING_EFFORT"] == "high"
    assert environment["MAINFLOW_CODEX_SERVICE_TIER"] == "fast"


def test_claude_builder_environment_applies_model_and_effort():
    service = _load_service_module()
    environment: dict[str, str] = {}

    service._configure_game_builder_environment(
        environment,
        "claude_code",
        model="opus",
        reasoning_effort="xhigh",
    )

    assert environment["MAINFLOW_CLAUDE_MODEL"] == "opus"
    assert environment["MAINFLOW_CLAUDE_REASONING_EFFORT"] == "xhigh"


def test_codex_default_model_defers_to_cli_configuration():
    service = _load_service_module()
    environment = {"MAINFLOW_CODEX_MODEL": "gpt-5.6-luna"}

    service._configure_game_builder_environment(
        environment,
        "codex_cli",
        model="default",
        reasoning_effort="medium",
    )

    assert environment["MAINFLOW_CODEX_MODEL"] == ""


def test_workflow_summary_extracts_failed_stage_and_features(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    service = _load_service_module()
    workspace = tmp_path / "workspace"
    project_id = "20261103_02"
    validation_root = workspace / project_id / "validation"
    validation_root.mkdir(parents=True)
    monkeypatch.setattr(service, "WORKSPACE_ROOT", workspace.resolve())
    message = (
        "Required generated features did not pass validation after bounded repairs: "
        "generated_feature_03: ValueError: missing scene objects; "
        "generated_feature_05: ValueError: unsupported Unity API; "
        "generated_feature_06: StructuredOutputError: token limit"
    )
    (validation_root / "game_generation_failure.json").write_text(
        json.dumps(
            {
                "status": "failed",
                "stage": "design_game_logic",
                "message": message,
            }
        ),
        encoding="utf-8",
    )
    result_path = tmp_path / "workflow_result.json"
    result_path.write_text(
        json.dumps(
            {
                "project_id": project_id,
                "game_validation": {
                    "status": "failed",
                    "issues": [
                        {
                            "code": "GAME_GENERATION_FAILED",
                            "severity": "error",
                            "message": message,
                        }
                    ],
                },
                "visual_validation": {
                    "status": "failed",
                    "summary": "Visual validation requires passed game validation",
                },
            }
        ),
        encoding="utf-8",
    )

    summary = service._summarize_workflow_result(result_path, 1)

    assert summary["project_id"] == project_id
    assert summary["failure_stage"] == "design_game_logic"
    assert summary["failed_features"] == [
        "generated_feature_03",
        "generated_feature_05",
        "generated_feature_06",
    ]
    assert "final_state" not in summary["error_summary"]

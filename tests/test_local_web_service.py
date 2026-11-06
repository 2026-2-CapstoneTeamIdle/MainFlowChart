from __future__ import annotations

import importlib.util
import json
import sys
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
        **_request_payload(),
    )
    assert request.game_builder == "codex_cli"


def test_generation_request_accepts_claude_code_builder():
    service = _load_service_module()
    request = service.GenerationRequest(
        mode="generate",
        game_builder="claude_code",
        **_request_payload(),
    )
    assert request.game_builder == "claude_code"


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


def test_codex_builder_environment_disables_api_backed_planning():
    service = _load_service_module()
    environment = {
        "MAINFLOW_CONDITION_FEATURE_PROVIDER": "openai",
        "MAINFLOW_DESIGN_V2_PROVIDER": "local",
    }
    service._configure_game_builder_environment(environment, "codex_cli")
    assert environment["MAINFLOW_GAME_BUILDER"] == "codex_cli"
    assert environment["MAINFLOW_CONDITION_FEATURE_PROVIDER"] == "off"
    assert environment["MAINFLOW_GENRE_FEATURE_PROVIDER"] == "off"
    assert environment["MAINFLOW_DESIGN_V2_PROVIDER"] == "deterministic"
    assert environment["MAINFLOW_BLUEPRINT_PROVIDER"] == "deterministic"
    assert environment["MAINFLOW_CODEX_STATIC_CHECKLISTS"] == "1"


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

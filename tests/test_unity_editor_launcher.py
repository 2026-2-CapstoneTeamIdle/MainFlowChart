from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from mainflow.unity_editor_launcher import UnityEditorAutoLauncher, open_unity_project


def _write_unity_project(workspace: Path, project_id: str) -> Path:
    project = workspace / project_id / "game" / "unity_project"
    settings = project / "ProjectSettings"
    settings.mkdir(parents=True)
    (settings / "ProjectVersion.txt").write_text("m_EditorVersion: 6000.0.71f1\n", encoding="utf-8")
    return project


def test_launcher_opens_project_created_after_capture(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_unity_project(workspace, "20261105_01")
    launcher = UnityEditorAutoLauncher.capture(workspace)
    generated = _write_unity_project(workspace, "20261105_02")
    unity = tmp_path / "Unity.exe"
    unity.write_bytes(b"")
    monkeypatch.setenv("UNITY_EDITOR_PATH", str(unity))
    monkeypatch.setenv("MAINFLOW_OPEN_UNITY_EDITOR", "1")

    with patch("mainflow.unity_editor_launcher.subprocess.Popen") as popen:
        opened = launcher.open_latest()

    assert opened == generated
    command = popen.call_args.args[0]
    assert command == [str(unity.resolve()), "-projectPath", str(generated)]
    assert popen.call_args.kwargs["stdin"] is subprocess.DEVNULL


def test_launcher_does_not_reopen_preexisting_project(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_unity_project(workspace, "20261105_01")
    launcher = UnityEditorAutoLauncher.capture(workspace)
    monkeypatch.setenv("MAINFLOW_OPEN_UNITY_EDITOR", "1")

    with patch("mainflow.unity_editor_launcher.subprocess.Popen") as popen:
        assert launcher.open_latest() is None

    popen.assert_not_called()


def test_launcher_can_be_disabled(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    launcher = UnityEditorAutoLauncher.capture(workspace)
    project = _write_unity_project(workspace, "20261105_01")
    report = tmp_path / "unity_project_path.txt"
    monkeypatch.setenv("MAINFLOW_OPEN_UNITY_EDITOR", "0")
    monkeypatch.setenv("MAINFLOW_UNITY_PROJECT_REPORT_FILE", str(report))

    with patch("mainflow.unity_editor_launcher.subprocess.Popen") as popen:
        assert launcher.open_latest() is None

    popen.assert_not_called()
    assert report.read_text(encoding="utf-8") == str(project.resolve())


def test_manual_open_ignores_auto_open_setting(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    project = _write_unity_project(workspace, "20261105_01")
    unity = tmp_path / "Unity.exe"
    unity.write_bytes(b"")
    monkeypatch.setenv("UNITY_EDITOR_PATH", str(unity))
    monkeypatch.setenv("MAINFLOW_OPEN_UNITY_EDITOR", "0")

    with patch("mainflow.unity_editor_launcher.subprocess.Popen") as popen:
        assert open_unity_project(project) == project

    popen.assert_called_once()

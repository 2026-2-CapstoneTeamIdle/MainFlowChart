from __future__ import annotations

import threading
from pathlib import Path

import pytest

from mainflow import webgl_preview


class _FakeUnityProcess:
    def __init__(self, command: list[str], *, succeeded: bool = True, **_kwargs: object) -> None:
        self.command = command
        self.pid = 1234
        output_root = Path(command[command.index("-webGLPreviewOutput") + 1])
        if succeeded:
            (output_root / "index.html").write_text("<html>preview</html>", encoding="utf-8")
            self.stdout = iter([f"{webgl_preview.WEBGL_SUCCESS_MARKER}{output_root}\n"])
            self.return_code = 0
        else:
            self.stdout = iter(["BuildFailedException: failed to build player\n"])
            self.return_code = 1

    def poll(self) -> int:
        return self.return_code

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        return self.return_code


class _LingeringStdoutUnityProcess(_FakeUnityProcess):
    """Model a Unity child process that keeps the inherited stdout pipe open."""

    def __init__(self, command: list[str], **kwargs: object) -> None:
        super().__init__(command, **kwargs)
        output_root = Path(command[command.index("-webGLPreviewOutput") + 1])
        never_closed = threading.Event()

        def output_lines():
            yield f"{webgl_preview.WEBGL_SUCCESS_MARKER}{output_root}\n"
            never_closed.wait(60)

        self.stdout = output_lines()


def _unity_project(tmp_path: Path) -> Path:
    project = tmp_path / "unity_project"
    settings = project / "ProjectSettings"
    settings.mkdir(parents=True)
    (settings / "ProjectVersion.txt").write_text("m_EditorVersion: 6000.0.71f1\n", encoding="utf-8")
    return project


def test_webgl_preview_build_publishes_staged_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    project = _unity_project(tmp_path)
    editor = tmp_path / "Unity.exe"
    editor.write_bytes(b"")
    output = tmp_path / "published" / "webgl"
    (output / "old.txt").parent.mkdir(parents=True)
    (output / "old.txt").write_text("old", encoding="utf-8")
    monkeypatch.setattr(
        webgl_preview.UnityProjectValidator,
        "find_unity_editor",
        lambda _version: editor,
    )
    monkeypatch.setattr(webgl_preview, "_has_webgl_support", lambda _editor: True)
    monkeypatch.setattr(
        webgl_preview.subprocess,
        "Popen",
        lambda command, **kwargs: _FakeUnityProcess(command, **kwargs),
    )

    result = webgl_preview.build_webgl_preview(project, output)

    assert result.output_root == output.resolve()
    assert (output / "index.html").read_text(encoding="utf-8") == "<html>preview</html>"
    assert not (output / "old.txt").exists()


def test_webgl_preview_failure_preserves_previous_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    project = _unity_project(tmp_path)
    editor = tmp_path / "Unity.exe"
    editor.write_bytes(b"")
    output = tmp_path / "published" / "webgl"
    output.mkdir(parents=True)
    (output / "index.html").write_text("old preview", encoding="utf-8")
    monkeypatch.setattr(
        webgl_preview.UnityProjectValidator,
        "find_unity_editor",
        lambda _version: editor,
    )
    monkeypatch.setattr(webgl_preview, "_has_webgl_support", lambda _editor: True)
    monkeypatch.setattr(
        webgl_preview.subprocess,
        "Popen",
        lambda command, **kwargs: _FakeUnityProcess(command, succeeded=False, **kwargs),
    )

    with pytest.raises(webgl_preview.WebGLPreviewBuildError, match="BuildFailedException"):
        webgl_preview.build_webgl_preview(project, output)

    assert (output / "index.html").read_text(encoding="utf-8") == "old preview"


def test_webgl_preview_publishes_when_child_keeps_stdout_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    project = _unity_project(tmp_path)
    editor = tmp_path / "Unity.exe"
    editor.write_bytes(b"")
    output = tmp_path / "published" / "webgl"
    monkeypatch.setattr(
        webgl_preview.UnityProjectValidator,
        "find_unity_editor",
        lambda _version: editor,
    )
    monkeypatch.setattr(webgl_preview, "_has_webgl_support", lambda _editor: True)
    monkeypatch.setattr(webgl_preview, "_POST_EXIT_OUTPUT_GRACE_SECONDS", 0.01)
    monkeypatch.setattr(
        webgl_preview.subprocess,
        "Popen",
        lambda command, **kwargs: _LingeringStdoutUnityProcess(command, **kwargs),
    )

    result = webgl_preview.build_webgl_preview(project, output, timeout_seconds=2)

    assert result.output_root == output.resolve()
    assert (output / "index.html").is_file()


def test_webgl_build_command_targets_webgl(tmp_path: Path):
    editor = tmp_path / "Unity.exe"
    project = tmp_path / "project"
    output = tmp_path / "output"

    command = webgl_preview._build_command(editor, project, output)

    assert command[command.index("-buildTarget") + 1] == "WebGL"
    assert command[command.index("-projectPath") + 1] == str(project)
    assert command[command.index("-webGLPreviewOutput") + 1] == str(output)
    assert (
        command[command.index("-executeMethod") + 1]
        == "TeamIdle.GameTemplate.Editor.WebGLPreviewBuilder.BuildForPreview"
    )


def test_webgl_preview_syncs_project_local_template(tmp_path: Path):
    project = _unity_project(tmp_path)

    webgl_preview._sync_preview_support(project)

    builder = project / "Assets/GameTemplate/Editor/WebGLPreviewBuilder.cs"
    template = project / "Assets/WebGLTemplates/TeamIdlePreview/index.html"
    builder_source = builder.read_text(encoding="utf-8")
    assert "PROJECT:TeamIdlePreview" in builder_source
    assert "WasmCodeOptimization.BuildTimes" in builder_source
    assert "BuildOptions.Development" in builder_source
    assert '"UI/Default Font"' in builder_source
    assert "LOADER_FILENAME" in template.read_text(encoding="utf-8")


def test_webgl_preview_uses_installed_editor_with_webgl_module(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    project = _unity_project(tmp_path)
    exact_editor = tmp_path / "6000.0.71f1" / "Unity.exe"
    webgl_editor = tmp_path / "6000.3.20f1" / "Unity.exe"
    exact_editor.parent.mkdir()
    webgl_editor.parent.mkdir()
    exact_editor.write_bytes(b"")
    webgl_editor.write_bytes(b"")
    output = tmp_path / "published" / "webgl"

    def find_editor(version: str | None = None) -> Path:
        return exact_editor if version else webgl_editor

    monkeypatch.delenv("UNITY_EDITOR_PATH", raising=False)
    monkeypatch.setattr(
        webgl_preview.UnityProjectValidator,
        "find_unity_editor",
        find_editor,
    )
    monkeypatch.setattr(
        webgl_preview,
        "_has_webgl_support",
        lambda editor: editor == webgl_editor,
    )
    monkeypatch.setattr(
        webgl_preview.subprocess,
        "Popen",
        lambda command, **kwargs: _FakeUnityProcess(command, **kwargs),
    )

    result = webgl_preview.build_webgl_preview(project, output)

    assert result.editor == webgl_editor.resolve()

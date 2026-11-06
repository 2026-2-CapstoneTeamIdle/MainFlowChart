"""Open the Unity project produced by a workflow, including failed workflows."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class UnityEditorAutoLauncher:
    workspace_root: Path
    existing_projects: frozenset[Path]

    @classmethod
    def capture(cls, workspace_root: Path) -> UnityEditorAutoLauncher:
        root = workspace_root.resolve()
        return cls(root, frozenset(_unity_projects(root)))

    def open_latest(self) -> Path | None:
        candidates = [
            path
            for path in _unity_projects(self.workspace_root)
            if path not in self.existing_projects
        ]
        if not candidates:
            print("[FLOW] 새 Unity 프로젝트가 생성되지 않아 Editor 자동 실행을 건너뜁니다.")
            return None
        project_root = max(
            candidates,
            key=lambda path: (path / "ProjectSettings/ProjectVersion.txt").stat().st_mtime_ns,
        )
        _write_project_report(project_root)
        if not _enabled():
            return None
        opened = open_unity_project(project_root)
        if opened is not None:
            print(f"[FLOW] 생성된 Unity 프로젝트를 Editor로 엽니다: {opened}")
        return opened


def open_unity_project(project_root: Path) -> Path | None:
    """Open one validated Unity project path in a detached Editor process."""

    project_root = project_root.resolve()
    if not (project_root / "ProjectSettings/ProjectVersion.txt").is_file():
        return None
    executable = _resolve_unity_editor(project_root)
    if executable is None:
        print(
            "[FLOW] Unity Editor 경로를 찾지 못해 자동 실행하지 못했습니다. "
            "UNITY_EDITOR_PATH를 설정하세요."
        )
        return None
    command = [str(executable), "-projectPath", str(project_root)]
    options: dict[str, object] = {
        "cwd": project_root,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        options["start_new_session"] = True
    try:
        subprocess.Popen(command, **options)
    except OSError as error:
        print(f"[FLOW] Unity Editor 자동 실행에 실패했습니다: {error}")
        return None
    return project_root


def _unity_projects(workspace_root: Path) -> list[Path]:
    if not workspace_root.is_dir():
        return []
    return [
        project
        for project in workspace_root.glob("*/game/unity_project")
        if (project / "ProjectSettings/ProjectVersion.txt").is_file()
    ]


def _resolve_unity_editor(project_root: Path) -> Path | None:
    configured = os.environ.get("UNITY_EDITOR_PATH", "").strip()
    if configured:
        executable = Path(configured).expanduser().resolve()
        if executable.is_file():
            return executable
    version_file = project_root / "ProjectSettings/ProjectVersion.txt"
    try:
        version_line = next(
            line
            for line in version_file.read_text(encoding="utf-8").splitlines()
            if line.startswith("m_EditorVersion:")
        )
    except (OSError, StopIteration):
        return None
    version = version_line.split(":", 1)[1].strip()
    if os.name == "nt" and version:
        installed = Path("C:/Program Files/Unity/Hub/Editor") / version / "Editor/Unity.exe"
        if installed.is_file():
            return installed.resolve()
    return None


def _enabled() -> bool:
    value = os.environ.get("MAINFLOW_OPEN_UNITY_EDITOR")
    if value is None:
        return os.environ.get("CI", "").strip().lower() not in {"1", "true", "yes"}
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _write_project_report(project_root: Path) -> None:
    configured = os.environ.get("MAINFLOW_UNITY_PROJECT_REPORT_FILE", "").strip()
    if not configured:
        return
    destination = Path(configured).resolve()
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(str(project_root.resolve()), encoding="utf-8")
    except OSError as error:
        print(f"[FLOW] Unity 프로젝트 경로 보고 파일을 쓰지 못했습니다: {error}")

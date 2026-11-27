"""Build a generated Unity project as a Windows player for an experiment."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BUILDER_SOURCE = ROOT / "tools" / "ExperimentStandaloneBuilder.cs"
BUILDER_DESTINATION = Path("Assets/GameTemplate/Editor/ExperimentStandaloneBuilder.cs")
SUCCESS_MARKER = "EXPERIMENT_BUILD_OK:"
INFRASTRUCTURE_MARKERS = (
    "no valid unity editor license",
    "license activation failed",
    "failed to activate license",
    "editor application path does not exist",
)


def resolve_editor(project_root: Path, configured: str | None = None) -> Path | None:
    candidate = configured or os.environ.get("UNITY_EDITOR_PATH", "").strip()
    if candidate:
        editor = Path(candidate).expanduser().resolve()
        return editor if editor.is_file() else None
    version_file = project_root / "ProjectSettings" / "ProjectVersion.txt"
    try:
        version = next(
            line.partition(":")[2].strip()
            for line in version_file.read_text(encoding="utf-8").splitlines()
            if line.startswith("m_EditorVersion:")
        )
    except (OSError, StopIteration):
        return None
    editor = Path("C:/Program Files/Unity/Hub/Editor") / version / "Editor/Unity.exe"
    return editor.resolve() if editor.is_file() else None


def build_command(editor: Path, project_root: Path, executable: Path, log_file: Path) -> list[str]:
    return [
        str(editor),
        "-batchmode",
        "-nographics",
        "-quit",
        "-buildTarget",
        "StandaloneWindows64",
        "-projectPath",
        str(project_root),
        "-executeMethod",
        "TeamIdle.GameTemplate.Editor.ExperimentStandaloneBuilder.Build",
        "-experimentOutput",
        str(executable),
        "-logFile",
        str(log_file),
    ]


def classify_player_build(
    exit_code: int, log_text: str, executable_exists: bool, *, timed_out: bool = False
) -> str:
    if timed_out:
        return "timed_out"
    if exit_code == 0 and SUCCESS_MARKER in log_text and executable_exists:
        return "passed"
    if any(marker in log_text.lower() for marker in INFRASTRUCTURE_MARKERS):
        return "infrastructure_error"
    return "failed"


def run_player_build(
    project_root: Path | None,
    trial_dir: Path,
    *,
    editor_path: str | None = None,
    timeout_minutes: float = 45,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "player_build_status": "not_attempted",
        "player_build_seconds": "",
        "player_build_exit_code": "",
        "player_build_log_file": "",
        "player_build_output": "",
        "player_build_error": "",
    }
    if project_root is None or not (project_root / "ProjectSettings/ProjectVersion.txt").is_file():
        return result
    editor = resolve_editor(project_root, editor_path)
    if editor is None:
        result["player_build_status"] = "infrastructure_error"
        result["player_build_error"] = "Unity Editor not found"
        return result
    if os.name != "nt":
        result["player_build_status"] = "infrastructure_error"
        result["player_build_error"] = "Windows player build requires a Windows host"
        return result
    try:
        destination = project_root / BUILDER_DESTINATION
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(BUILDER_SOURCE, destination)
        trial_dir.mkdir(parents=True, exist_ok=True)
        executable = trial_dir / "Game.exe"
        editor_log = trial_dir / "unity_build.log"
        launcher_log = trial_dir / "unity_launcher.log"
        executable.unlink(missing_ok=True)
        result["player_build_log_file"] = str(editor_log)
        result["player_build_output"] = str(executable)
        command = build_command(editor, project_root, executable, editor_log)
        started = time.monotonic()
        with launcher_log.open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                command,
                cwd=ROOT,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
            try:
                exit_code = process.wait(timeout=timeout_minutes * 60)
            except subprocess.TimeoutExpired:
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
                process.wait()
                exit_code = process.returncode or -1
                result["player_build_status"] = "timed_out"
            except KeyboardInterrupt:
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
                process.wait()
                raise
    except OSError as error:
        result["player_build_status"] = "infrastructure_error"
        result["player_build_error"] = str(error)
        return result
    result["player_build_seconds"] = round(time.monotonic() - started, 1)
    result["player_build_exit_code"] = exit_code
    try:
        log_text = editor_log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        log_text = ""
    result["player_build_status"] = classify_player_build(
        exit_code,
        log_text,
        executable.is_file(),
        timed_out=result["player_build_status"] == "timed_out",
    )
    return result

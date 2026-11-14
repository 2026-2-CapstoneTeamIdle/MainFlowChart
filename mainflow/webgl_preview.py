"""Build and publish a generated Unity project's loopback-only WebGL preview."""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Queue

from game_pipeline.unity_project_validator import UnityProjectValidator

WEBGL_SUCCESS_MARKER = "UNITY_WEBGL_PREVIEW_OK:"
_POST_EXIT_OUTPUT_GRACE_SECONDS = 1.0
_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_PREVIEW_BUILDER_RELATIVE_PATH = Path("Assets/GameTemplate/Editor/WebGLPreviewBuilder.cs")
_PREVIEW_TEMPLATE_RELATIVE_PATH = Path("Assets/WebGLTemplates/TeamIdlePreview")


@dataclass(frozen=True)
class WebGLPreviewResult:
    """Published WebGL output and build diagnostics."""

    output_root: Path
    editor: Path
    elapsed_seconds: float


class WebGLPreviewBuildError(RuntimeError):
    """Raised when a Unity WebGL preview cannot be built or published."""


def build_webgl_preview(
    project_root: str | Path,
    output_root: str | Path,
    *,
    timeout_seconds: int | None = None,
    on_log: Callable[[str], None] | None = None,
    on_process: Callable[[subprocess.Popen[str] | None], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> WebGLPreviewResult:
    """Build into a staging directory and replace the published preview on success."""

    project = Path(project_root).resolve()
    output = Path(output_root).resolve()
    if not (project / "ProjectSettings/ProjectVersion.txt").is_file():
        raise WebGLPreviewBuildError(f"Unity 프로젝트가 아닙니다: {project}")

    required_version = _read_project_version(project)
    editor = UnityProjectValidator.find_unity_editor(required_version)
    if editor is None or not editor.is_file():
        raise WebGLPreviewBuildError(
            "Unity Editor를 찾지 못했습니다. UNITY_EDITOR_PATH를 설정하세요."
        )
    if not _has_webgl_support(editor):
        fallback = None
        if not os.environ.get("UNITY_EDITOR_PATH", "").strip():
            candidate = UnityProjectValidator.find_unity_editor()
            if candidate is not None and candidate.is_file() and _has_webgl_support(candidate):
                fallback = candidate
        if fallback is None:
            raise WebGLPreviewBuildError(
                "설치된 Unity Editor에 WebGL Build Support 모듈이 없습니다. "
                "Unity Hub에서 WebGL Build Support를 추가하거나, 모듈이 설치된 Editor를 "
                "UNITY_EDITOR_PATH로 지정하세요."
            )
        editor = fallback

    _sync_preview_support(project)

    timeout = timeout_seconds or _timeout_seconds()
    staging = output.parent / f".{output.name}-staging-{uuid.uuid4().hex}"
    backup = output.parent / f".{output.name}-backup-{uuid.uuid4().hex}"
    staging.mkdir(parents=True, exist_ok=False)
    command = _build_command(editor, project, staging)
    emit = on_log or (lambda _line: None)
    started = time.monotonic()
    process: subprocess.Popen[str] | None = None
    lines: list[str] = []
    try:
        if is_cancelled is not None and is_cancelled():
            raise WebGLPreviewBuildError("WebGL Preview 빌드가 시작 전에 취소되었습니다.")
        emit(f"[WEBGL] Unity {editor}로 Preview 빌드를 시작합니다.")
        process_options: dict[str, object] = {}
        if os.name == "nt":
            process_options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            process_options["start_new_session"] = True
        process = subprocess.Popen(
            command,
            cwd=project,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            **process_options,
        )
        if on_process is not None:
            on_process(process)
        assert process.stdout is not None
        deadline = started + timeout
        output_queue: Queue[str | None] = Queue()

        def read_output() -> None:
            assert process is not None and process.stdout is not None
            for line in process.stdout:
                output_queue.put(line)
            output_queue.put(None)

        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()
        process_exited_at: float | None = None
        last_output_at = time.monotonic()
        while True:
            if is_cancelled is not None and is_cancelled():
                _terminate_process(process)
                raise WebGLPreviewBuildError("WebGL Preview 빌드가 취소되었습니다.")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _terminate_process(process)
                raise WebGLPreviewBuildError(
                    f"WebGL Preview 빌드가 {timeout}초 제한을 초과했습니다."
                )
            try:
                line = output_queue.get(timeout=min(1.0, remaining))
            except Empty:
                # Unity may leave Package Manager or Licensing descendants holding
                # the inherited stdout descriptor open.  In that case the Unity
                # process is already a zombie, but the reader never observes EOF
                # and LocalWeb remains in ``preview_status=building`` forever.
                # Polling reaps Unity itself; after a short quiet period the output
                # collected so far is complete enough to validate the explicit
                # success marker and generated index.html.
                if process.poll() is not None:
                    now = time.monotonic()
                    if process_exited_at is None:
                        process_exited_at = now
                    quiet_since = max(process_exited_at, last_output_at)
                    if now - quiet_since >= _POST_EXIT_OUTPUT_GRACE_SECONDS:
                        break
                continue
            if line is None:
                break
            normalized = line.rstrip("\r\n")
            lines.append(normalized)
            emit(normalized)
            last_output_at = time.monotonic()
        return_code = process.wait(timeout=max(1.0, deadline - time.monotonic()))
        combined_log = "\n".join(lines)
        index_path = staging / "index.html"
        if return_code != 0 or WEBGL_SUCCESS_MARKER not in combined_log or not index_path.is_file():
            detail = _failure_detail(combined_log, return_code)
            raise WebGLPreviewBuildError(f"Unity WebGL 빌드 실패: {detail}")

        output.parent.mkdir(parents=True, exist_ok=True)
        if output.exists():
            output.replace(backup)
        try:
            staging.replace(output)
        except OSError:
            if backup.exists() and not output.exists():
                backup.replace(output)
            raise
        shutil.rmtree(backup, ignore_errors=True)
        elapsed = time.monotonic() - started
        emit(f"[WEBGL] Preview 빌드가 완료되었습니다. ({elapsed:.1f}초)")
        return WebGLPreviewResult(output, editor.resolve(), elapsed)
    except (OSError, subprocess.SubprocessError) as error:
        raise WebGLPreviewBuildError(f"Unity WebGL 빌드 실행 실패: {error}") from error
    finally:
        if on_process is not None:
            on_process(None)
        if process is not None and process.poll() is None:
            _terminate_process(process)
        shutil.rmtree(staging, ignore_errors=True)


def _build_command(editor: Path, project_root: Path, output_root: Path) -> list[str]:
    return [
        str(editor),
        "-batchmode",
        "-nographics",
        "-quit",
        "-buildTarget",
        "WebGL",
        "-projectPath",
        str(project_root),
        "-executeMethod",
        "TeamIdle.GameTemplate.Editor.WebGLPreviewBuilder.BuildForPreview",
        "-webGLPreviewOutput",
        str(output_root),
        "-logFile",
        "-",
    ]


def _sync_preview_support(project_root: Path) -> None:
    """Install repository-owned preview tooling into old and new generated projects."""

    source_root = _REPOSITORY_ROOT / "unity_template"
    source_builder = source_root / _PREVIEW_BUILDER_RELATIVE_PATH
    source_template = source_root / _PREVIEW_TEMPLATE_RELATIVE_PATH
    if not source_builder.is_file() or not (source_template / "index.html").is_file():
        raise WebGLPreviewBuildError("LocalWeb WebGL Preview 지원 파일을 찾지 못했습니다.")

    destination_builder = project_root / _PREVIEW_BUILDER_RELATIVE_PATH
    destination_template = project_root / _PREVIEW_TEMPLATE_RELATIVE_PATH
    try:
        destination_builder.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_builder, destination_builder)
        shutil.copytree(source_template, destination_template, dirs_exist_ok=True)
    except OSError as error:
        raise WebGLPreviewBuildError(
            f"Unity 프로젝트에 WebGL Preview 지원 파일을 준비하지 못했습니다: {error}"
        ) from error


def _read_project_version(project_root: Path) -> str | None:
    try:
        for line in (
            (project_root / "ProjectSettings/ProjectVersion.txt")
            .read_text(encoding="utf-8")
            .splitlines()
        ):
            if line.startswith("m_EditorVersion:"):
                return line.partition(":")[2].strip() or None
    except OSError:
        return None
    return None


def _has_webgl_support(editor: Path) -> bool:
    if os.name == "nt":
        root = editor.parent / "Data" / "PlaybackEngines" / "WebGLSupport"
    elif editor.name == "Unity" and editor.parent.name == "MacOS":
        root = editor.parent.parent / "PlaybackEngines" / "WebGLSupport"
    else:
        root = editor.parent / "Data" / "PlaybackEngines" / "WebGLSupport"
    return root.is_dir()


def _timeout_seconds() -> int:
    raw = os.environ.get("MAINFLOW_WEBGL_BUILD_TIMEOUT_SECONDS", "1200")
    try:
        value = int(raw)
    except ValueError:
        value = 1200
    return max(value, 60)


def _failure_detail(log: str, return_code: int) -> str:
    tokens = (
        "error CS",
        "BuildFailedException",
        "InvalidOperationException:",
        "No valid Unity Editor license found",
        "another Unity instance is running",
        "project already open",
        "Aborting batchmode",
    )
    details = [
        line.strip()
        for line in log.splitlines()
        if line.strip() and any(token in line for token in tokens)
    ]
    if details:
        return " | ".join(dict.fromkeys(details[:3]))
    return f"Unity 종료 코드 {return_code}; 성공 마커 또는 index.html이 없습니다."


def _terminate_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        else:
            os.killpg(process.pid, 15)
            process.wait(timeout=10)
    except (OSError, subprocess.SubprocessError):
        process.kill()

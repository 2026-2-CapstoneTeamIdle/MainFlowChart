"""In-memory device-login coordination for the containerized Codex CLI."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
from collections import deque
from pathlib import Path
from typing import Any

_ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_URL_PATTERN = re.compile(r"https://[^\s]+")
_DEVICE_CODE_PATTERN = re.compile(r"\b[A-Z0-9]{4}(?:-[A-Z0-9]{4})+\b", re.IGNORECASE)


class CodexAuthManager:
    """Start one device login and expose only localhost-safe status details."""

    def __init__(self, executable: str | Path | None = None) -> None:
        self._executable = str(executable) if executable else _find_codex_executable()
        self._lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None
        self._output: deque[str] = deque(maxlen=30)
        self._auth_url: str | None = None
        self._device_code: str | None = None
        self._last_error: str | None = None

    def snapshot(self) -> dict[str, Any]:
        """Return installation, login, and active device-flow state."""

        with self._lock:
            process = self._process
            if process is not None and process.poll() is None:
                return self._pending_snapshot()
            last_error = self._last_error

        if not self._executable:
            return {
                "installed": False,
                "authenticated": False,
                "phase": "unavailable",
                "version": None,
                "message": "Docker 이미지에 Codex CLI가 설치되어 있지 않습니다.",
                "auth_url": None,
                "device_code": None,
                "output": "",
            }

        version = _run_codex(self._executable, ["--version"])
        if version.returncode != 0:
            return {
                "installed": False,
                "authenticated": False,
                "phase": "unavailable",
                "version": None,
                "message": _command_message(version, "Codex CLI를 실행하지 못했습니다."),
                "auth_url": None,
                "device_code": None,
                "output": "",
            }

        login = _run_codex(self._executable, ["login", "status"])
        authenticated = login.returncode == 0
        phase = "authenticated" if authenticated else ("failed" if last_error else "signed_out")
        if authenticated:
            message = _command_message(login, "Codex 로그인이 확인되었습니다.")
            with self._lock:
                self._last_error = None
                self._output.clear()
                self._auth_url = None
                self._device_code = None
        elif last_error:
            message = last_error
        else:
            message = "Codex를 사용하려면 Device Code 로그인이 필요합니다."
        return {
            "installed": True,
            "authenticated": authenticated,
            "phase": phase,
            "version": _command_message(version, "Codex CLI"),
            "message": message,
            "auth_url": None,
            "device_code": None,
            "output": "",
        }

    def start_device_login(self) -> dict[str, Any]:
        """Start the official headless device-code login without persisting its output."""

        current = self.snapshot()
        if current["authenticated"] or current["phase"] == "pending":
            return current
        if not self._executable:
            raise FileNotFoundError("Codex CLI가 설치되어 있지 않습니다.")

        with self._lock:
            if self._process is not None and self._process.poll() is None:
                return self._pending_snapshot()
            self._output.clear()
            self._auth_url = None
            self._device_code = None
            self._last_error = None
            try:
                process = subprocess.Popen(
                    [self._executable, "login", "--device-auth"],
                    env=_codex_login_environment(),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                )
            except OSError as error:
                raise RuntimeError(
                    f"Codex Device Code 로그인을 시작하지 못했습니다: {error}"
                ) from error
            self._process = process

        threading.Thread(
            target=self._collect_login_output,
            args=(process,),
            daemon=True,
            name="codex-device-login",
        ).start()
        return self.snapshot()

    def logout(self) -> dict[str, Any]:
        """Remove only the credentials stored in the Docker Codex auth volume."""

        if not self._executable:
            raise FileNotFoundError("Codex CLI가 설치되어 있지 않습니다.")

        with self._lock:
            if self._process is not None and self._process.poll() is None:
                raise RuntimeError("Device Code 로그인이 진행 중일 때는 로그아웃할 수 없습니다.")

        result = _run_codex(self._executable, ["logout"])
        if result.returncode != 0:
            raise RuntimeError(_command_message(result, "Codex 로그아웃에 실패했습니다."))

        with self._lock:
            self._last_error = None
            self._output.clear()
            self._auth_url = None
            self._device_code = None
        return self.snapshot()

    def _collect_login_output(self, process: subprocess.Popen[str]) -> None:
        stream = process.stdout
        if stream is not None:
            for raw_line in stream:
                line = _clean_output(raw_line)
                if not line:
                    continue
                with self._lock:
                    self._output.append(line)
                    if self._auth_url is None:
                        match = _URL_PATTERN.search(line)
                        if match:
                            self._auth_url = match.group(0).rstrip(".,)")
                    if self._device_code is None:
                        match = _DEVICE_CODE_PATTERN.search(line)
                        if match:
                            self._device_code = match.group(0).upper()
        return_code = process.wait()
        with self._lock:
            if self._process is process:
                self._process = None
            if return_code == 0:
                self._last_error = None
                self._output.clear()
                self._auth_url = None
                self._device_code = None
            else:
                detail = self._output[-1] if self._output else f"종료 코드 {return_code}"
                self._last_error = f"Codex 로그인이 완료되지 않았습니다: {detail}"

    def _pending_snapshot(self) -> dict[str, Any]:
        return {
            "installed": True,
            "authenticated": False,
            "phase": "pending",
            "version": None,
            "message": "브라우저에서 Device Code 로그인을 완료하세요.",
            "auth_url": self._auth_url,
            "device_code": self._device_code,
            "output": "\n".join(self._output),
        }


def _find_codex_executable() -> str | None:
    configured = os.environ.get("MAINFLOW_CODEX_CLI_PATH", "").strip()
    if configured:
        path = Path(configured)
        if path.is_file():
            return str(path)
    return shutil.which("codex")


def _run_codex(executable: str, arguments: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            [executable, *arguments],
            env=_codex_login_environment(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return subprocess.CompletedProcess(
            [executable, *arguments],
            1,
            "",
            f"{type(error).__name__}: {error}",
        )


def _codex_login_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for name in ("OPENAI_API_KEY", "CODEX_ACCESS_TOKEN"):
        environment.pop(name, None)
    environment["NO_COLOR"] = "1"
    environment["TERM"] = "dumb"
    return environment


def _command_message(result: subprocess.CompletedProcess[str], fallback: str) -> str:
    output = _clean_output(f"{result.stdout}\n{result.stderr}")
    return output[:500] or fallback


def _clean_output(value: str) -> str:
    return _ANSI_ESCAPE.sub("", value).strip()

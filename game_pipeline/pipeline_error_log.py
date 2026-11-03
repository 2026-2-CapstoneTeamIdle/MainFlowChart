"""Append project-scoped AI and validation failures without masking the root error."""

from __future__ import annotations

import hashlib
import threading
from datetime import datetime, timedelta, timezone

from mainflow.ArtifactManager import ArtifactManager
from MCP.node_context import get_current_mcp_manager

ERROR_LOG_PATH = "validation/errorlog.md"
_LOG_LOCK = threading.Lock()
_KST = timezone(timedelta(hours=9), name="KST")


def current_project_id() -> str | None:
    """Return the project bound to the current workflow node, if one exists."""

    try:
        return get_current_mcp_manager().project_id
    except RuntimeError:
        return None


def append_pipeline_error(
    stage: str,
    reason: str,
    detail: str,
    *,
    project_id: str | None = None,
) -> bool:
    """Append one Markdown row and never replace the original pipeline exception."""

    resolved_project_id = project_id or current_project_id()
    if not resolved_project_id:
        return False
    row = "|".join(
        (
            _cell(datetime.now(_KST).isoformat(timespec="seconds")),
            _cell(stage),
            _cell(reason),
            _cell(detail),
        )
    )
    header = "# Pipeline Error Log\n\n날짜|시점|이유|상세\n---|---|---|---\n"
    try:
        with _LOG_LOCK:
            manager = ArtifactManager()
            path = manager.resolve_project_path(resolved_project_id, ERROR_LOG_PATH)
            if path.is_file():
                existing = path.read_text(encoding="utf-8")
                expected_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
            else:
                existing = header
                expected_sha256 = None
            manager.write_project_text(
                resolved_project_id,
                ERROR_LOG_PATH,
                existing.rstrip() + "\n" + row + "\n",
                expected_sha256=expected_sha256,
            )
        return True
    except (OSError, TypeError, ValueError):
        # Diagnostic persistence must never hide the actual generation/validation failure.
        return False


def _cell(value: object) -> str:
    return (
        str(value).strip().replace("|", "\\|").replace("\r\n", "<br>").replace("\n", "<br>")[:4000]
    )

"""Structured JSON checklist generation through the selected Claude Code CLI."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from threading import Lock
from typing import Any

from game_pipeline.claude_code.config import ClaudeCodeHarnessSettings
from game_pipeline.claude_code.runner import ClaudeCodeCliRunner


class ClaudeStructuredJsonClient:
    def __init__(self, project_root: Path, role: str) -> None:
        self.project_root = project_root
        self.role = role
        self.request_number = 0
        self._request_lock = Lock()

    def generate_json(self, prompt: str, schema: Mapping[str, Any]) -> Mapping[str, Any]:
        with self._request_lock:
            self.request_number += 1
            request_number = self.request_number
        result = ClaudeCodeCliRunner(ClaudeCodeHarnessSettings.from_environment()).run(
            project_root=self.project_root,
            prompt=(
                "Analyze the game requirements only. Do not edit files or run commands. "
                "Return one JSON object matching the provided schema.\n\n" + prompt
            ),
            schema=dict(schema),
            audit_directory=(
                self.project_root
                / "validation"
                / "claude_feature_analysis"
                / self.role
                / f"request_{request_number:03d}"
            ),
            sandbox="read-only",
        )
        return result.final_response

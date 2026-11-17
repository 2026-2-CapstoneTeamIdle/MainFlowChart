"""Structured JSON feature analysis through the authenticated Codex CLI."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from game_pipeline.codex_cli.config import CodexHarnessSettings
from game_pipeline.codex_cli.runner import CodexCliRunner


class CodexStructuredJsonClient:
    """Use Codex as a read-only requirements analyst with auditable responses."""

    def __init__(self, project_root: Path, role: str, model_environment: str) -> None:
        self.project_root = project_root
        self.role = role
        self.model_environment = model_environment
        self.request_number = 0

    def generate_json(self, prompt: str, schema: Mapping[str, Any]) -> Mapping[str, Any]:
        settings = CodexHarnessSettings.from_environment()
        selected_model = os.environ.get(self.model_environment, "builder").strip()
        if selected_model and selected_model != "builder":
            settings = replace(settings, model=selected_model)
        self.request_number += 1
        result = CodexCliRunner(settings).run(
            project_root=self.project_root,
            prompt=(
                "Analyze the game requirements only. Do not edit files or run commands. "
                "Return one JSON object matching the provided schema.\n\n" + prompt
            ),
            schema=dict(schema),
            audit_directory=(
                self.project_root
                / "validation"
                / "codex_feature_analysis"
                / self.role
                / f"request_{self.request_number:03d}"
            ),
            sandbox="read-only",
        )
        return result.final_response

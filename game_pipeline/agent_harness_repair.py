"""Reconnect downstream Unity validation failures to the configured CLI agent harness."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from game_pipeline.codex_cli.config import CodexHarnessSettings, resolve_game_builder
from game_pipeline.codex_cli.harness import (
    AgentPostValidationRepairResult,
    CodexGameHarness,
)
from game_pipeline.unity_project_validator import UnityValidationOutcome
from mainflow.contracts import GameLogicDraft, ParsedRequest


def repair_with_configured_agent_harness(
    *,
    project_root: Path,
    workspace_root: Path,
    draft: GameLogicDraft,
    request: ParsedRequest,
    initial_outcome: UnityValidationOutcome,
    phase: str,
    record: Callable[[str, Any], None] | None = None,
) -> AgentPostValidationRepairResult | None:
    """Repair only Codex/Claude projects; ordinary pipeline behavior remains unchanged."""

    builder = resolve_game_builder()
    if builder == "pipeline" or initial_outcome.status == "passed":
        return None
    max_repairs = _post_validation_repairs()
    if builder == "codex_cli":
        settings = CodexHarnessSettings.from_environment()
        harness = CodexGameHarness(
            settings,
            audit_root=workspace_root / "validation" / "codex" / "downstream",
            record=record,
        )
    else:
        from game_pipeline.claude_code import ClaudeCodeGameHarness
        from game_pipeline.claude_code.config import ClaudeCodeHarnessSettings

        settings = ClaudeCodeHarnessSettings.from_environment()
        harness = ClaudeCodeGameHarness(
            settings,
            audit_root=workspace_root / "validation" / "claude_code" / "downstream",
            record=record,
        )
    return harness.repair_existing_project(
        project_root=project_root,
        draft=draft,
        request=request,
        initial_outcome=initial_outcome,
        phase=phase,
        max_repairs=min(max_repairs, settings.max_repairs),
    )


def repair_feature_audit_with_configured_agent(
    *,
    project_root: Path,
    workspace_root: Path,
    draft: GameLogicDraft,
    request: ParsedRequest,
    findings: list[dict[str, Any]],
    iteration: int,
) -> UnityValidationOutcome | None:
    """Repair source-grounded missing requirements, then rerun Unity validation."""
    builder = resolve_game_builder()
    if builder == "pipeline" or not findings:
        return None
    if builder == "codex_cli":
        settings = CodexHarnessSettings.from_environment()
        harness = CodexGameHarness(
            settings, audit_root=workspace_root / "validation" / "codex" / "feature_audit_repair"
        )
    else:
        from game_pipeline.claude_code import ClaudeCodeGameHarness
        from game_pipeline.claude_code.config import ClaudeCodeHarnessSettings

        settings = ClaudeCodeHarnessSettings.from_environment()
        harness = ClaudeCodeGameHarness(
            settings,
            audit_root=workspace_root / "validation" / "claude_code" / "feature_audit_repair",
        )
    return harness.repair_quality_findings(
        project_root=project_root,
        draft=draft,
        request=request,
        findings=findings,
        iteration=iteration,
    )


def _post_validation_repairs() -> int:
    name = "MAINFLOW_AGENT_POST_VALIDATION_REPAIRS"
    try:
        value = int(os.environ.get(name, "3"))
    except ValueError as error:
        raise ValueError(f"{name} must be an integer") from error
    if not 1 <= value <= 6:
        raise ValueError(f"{name} must be between 1 and 6")
    return value

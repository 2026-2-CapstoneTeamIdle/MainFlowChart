"""Claude Code-backed whole-project game implementation harness."""

import json

from game_pipeline.claude_code.config import ClaudeCodeHarnessSettings
from game_pipeline.claude_code.preflight import run_claude_code_preflight
from game_pipeline.claude_code.runner import ClaudeCodeCliRunner
from game_pipeline.codex_cli.harness import QUALITY_REVIEW_SCHEMA, CodexGameHarness
from mainflow.contracts import CONTRACT_VERSION


class ClaudeCodeGameHarness(CodexGameHarness):
    """Use Claude Code with the same deterministic Unity validation and repair loop."""

    def __init__(self, settings, *, audit_root, record=None) -> None:
        super().__init__(
            settings,
            audit_root=audit_root,
            record=record,
            runner=ClaudeCodeCliRunner(settings),
            preflight_runner=run_claude_code_preflight,
            provider="claude_code",
            agent_label="Claude Code",
            instruction_filename="CLAUDE.md",
            total_timeout_environment="MAINFLOW_CLAUDE_TOTAL_TIMEOUT_SECONDS",
        )


def run_claude_code_quality_review(*, project_root, project_id, evidence):
    """Run the final read-only audit through the user's Claude Code session."""

    settings = ClaudeCodeHarnessSettings.from_environment()
    preflight = run_claude_code_preflight(settings)
    prompt = f"""Independently audit the completed Unity game for project {project_id}.

This is a read-only quality review. Do not edit any file. Read
`game/project_context_index.json`, generated design documents, relevant Unity runtime scripts,
and validation records. Check requirement coverage, connected gameplay, progression, content,
balance, presentation, and asset integration. Hard validator failures cannot be overruled. Cite
project-relative paths or hard check IDs for every nontrivial conclusion.
If the image backend deliberately produced placeholders and visual validation is marked skipped,
record that as a limitation; do not fail solely because no real image asset was applied. Prefer
post-quality Unity validation evidence over the earlier pre-repair run when available.

HOST EVIDENCE:
{json.dumps(evidence, ensure_ascii=False, indent=2)}
"""
    result = ClaudeCodeCliRunner(settings).run(
        project_root=project_root,
        prompt=prompt,
        schema=QUALITY_REVIEW_SCHEMA,
        audit_directory=project_root / "validation" / "claude_code" / "final_quality_review",
        sandbox="read-only",
    )
    return {
        "report_version": "1.0.0",
        "contract_version": CONTRACT_VERSION,
        **result.final_response,
        "provider": "claude_code",
        "model": settings.model or "user-default",
        "attempts": 1,
        "turns": 1,
        "tool_calls": [],
        "claude_code_preflight": preflight.to_dict(),
    }


__all__ = [
    "ClaudeCodeCliRunner",
    "ClaudeCodeGameHarness",
    "ClaudeCodeHarnessSettings",
    "run_claude_code_preflight",
    "run_claude_code_quality_review",
]

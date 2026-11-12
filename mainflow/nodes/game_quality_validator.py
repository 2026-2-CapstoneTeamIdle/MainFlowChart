"""Run an independent AI quality audit after all deterministic validation."""

from __future__ import annotations

import os
from typing import Any, cast

from game_pipeline import (
    create_game_quality_validator_from_environment,
    resolve_feature_provider_from_environment,
    run_claude_code_quality_review,
    run_codex_quality_review,
)
from mainflow.ArtifactManager import ArtifactManager
from mainflow.contracts import (
    CONTRACT_VERSION,
    GameValidatorAIAgentInput,
    GameValidatorAIAgentOutput,
    GameValidatorAIResult,
)
from mainflow.nodes._common import log


def game_quality_validator_node(
    state: GameValidatorAIAgentInput,
) -> GameValidatorAIAgentOutput:
    """Evaluate the completed game without allowing the AI to modify it."""

    log("독립 Validator AI가 요구사항, 플레이 흐름, 콘텐츠와 검증 증거를 종합 평가합니다.")
    manager = ArtifactManager()
    keys = [
        "parsed_request",
        "logic_analysis",
        "game_logic_draft",
        "game_validation_result",
        "image_validation_result",
        "sound_validation_result",
        "integrated_game",
        "final_validation_result",
    ]
    if "visual_validation_result" in state:
        keys.append("visual_validation_result")
    try:
        evidence: dict[str, Any] = {}
        for key in keys:
            reference = state[key]
            if reference["project_id"] != state["project_id"]:
                raise ValueError(f"Cross-project Validator AI input: {key}")
            evidence[key] = manager.read_json(reference)

        final_result = evidence["final_validation_result"]
        if final_result.get("status") != "passed":
            report = _hard_failure_report(evidence)
        elif os.environ.get("MAINFLOW_GAME_VALIDATOR_ENABLED", "1").strip().lower() in {
            "0",
            "false",
            "no",
            "off",
        }:
            report = _disabled_report()
        elif os.environ.get("MAINFLOW_GAME_BUILDER", "").strip().lower() == "codex_cli":
            report = cast(
                GameValidatorAIResult,
                run_codex_quality_review(
                    project_root=manager.ensure_project(state["project_id"]),
                    project_id=state["project_id"],
                    evidence=evidence,
                ),
            )
        elif os.environ.get("MAINFLOW_GAME_BUILDER", "").strip().lower() == "claude_code":
            report = cast(
                GameValidatorAIResult,
                run_claude_code_quality_review(
                    project_root=manager.ensure_project(state["project_id"]),
                    project_id=state["project_id"],
                    evidence=evidence,
                ),
            )
        else:
            provider = resolve_feature_provider_from_environment()
            validator = create_game_quality_validator_from_environment(
                state["project_id"], provider=provider
            )
            ai_report = validator.evaluate(state["project_id"], evidence)
            report = cast(
                GameValidatorAIResult, {"contract_version": CONTRACT_VERSION, **ai_report}
            )
        if (
            final_result.get("status") == "passed"
            and report.get("status") == "needs_revision"
            and os.environ.get("MAINFLOW_GAME_BUILDER", "").strip().lower()
            in {"codex_cli", "claude_code"}
        ):
            report = _repair_and_review_quality(state["project_id"], manager, evidence, report)
    except Exception as error:  # noqa: BLE001 - preserve a report at the final workflow boundary
        report = _execution_failure_report(error)

    return {
        "game_validator_ai_result": manager.write_json(
            state["project_id"],
            "validation",
            "game_validator_ai_result.json",
            report,
            producer="game_quality_validator",
        )
    }


def _repair_and_review_quality(
    project_id: str,
    manager: ArtifactManager,
    evidence: dict[str, Any],
    initial_report: GameValidatorAIResult,
) -> GameValidatorAIResult:
    """Use the builder to fix evidenced quality gaps, with Unity as the safety gate."""

    from game_pipeline.codex_cli import CodexGameHarness, CodexHarnessSettings

    builder = os.environ["MAINFLOW_GAME_BUILDER"].strip().lower()
    max_repairs = int(os.environ.get("MAINFLOW_GAME_QUALITY_REPAIRS", "2"))
    if not 0 <= max_repairs <= 3:
        raise ValueError("MAINFLOW_GAME_QUALITY_REPAIRS must be between 0 and 3")
    if not max_repairs:
        return initial_report
    workspace = manager.ensure_project(project_id)
    project_root = workspace / "game" / "unity_project"
    record = lambda name, data: manager.write_json(
        project_id,
        "validation",
        f"quality_repair/{name}.json",
        data,
        producer="game_quality_validator",
    )
    if builder == "codex_cli":
        harness = CodexGameHarness(
            CodexHarnessSettings.from_environment(),
            audit_root=workspace / "validation" / "codex" / "quality_repair",
            record=record,
        )
        review = run_codex_quality_review
    else:
        from game_pipeline.claude_code import ClaudeCodeGameHarness
        from game_pipeline.claude_code.config import ClaudeCodeHarnessSettings

        harness = ClaudeCodeGameHarness(
            ClaudeCodeHarnessSettings.from_environment(),
            audit_root=workspace / "validation" / "claude_code" / "quality_repair",
            record=record,
        )
        review = run_claude_code_quality_review

    report = initial_report
    previous_repair_error = ""
    record("audit_00", report)
    for attempt in range(1, max_repairs + 1):
        actionable = [
            finding
            for finding in report.get("findings", [])
            if finding.get("severity") in {"error", "warning"}
            and finding.get("category")
            in {
                "requirement",
                "gameplay",
                "content",
                "presentation",
                "progression",
                "balance",
                "integration",
                "evidence",
            }
            and "placeholder" not in finding.get("message", "").lower()
            and any(
                "game/unity_project/Assets/" in str(path).replace("\\", "/")
                or str(path).replace("\\", "/").startswith("Assets/")
                for path in finding.get("evidence", [])
            )
        ]
        if not actionable:
            break
        if previous_repair_error:
            actionable.append(
                {
                    "severity": "error",
                    "category": "integration",
                    "message": (
                        "The previous quality patch was rolled back after Unity validation. "
                        "Use a different, compile-safe implementation and first resolve this "
                        f"failure: {previous_repair_error}"
                    ),
                    "evidence": [],
                }
            )
        log(f"독립 품질 평가의 기능 누락을 CLI Agent가 수정합니다 ({attempt}/{max_repairs}).")
        try:
            outcome = harness.repair_quality_findings(
                project_root=project_root,
                draft=evidence["game_logic_draft"],
                request=evidence["parsed_request"],
                findings=actionable,
                iteration=attempt,
            )
            evidence["post_quality_unity_validation"] = {
                "status": outcome.status,
                "checks": outcome.checks,
                "issues": outcome.issues,
                "unity_log": outcome.unity_log[-12000:],
            }
            record(f"unity_validation_{attempt:02d}", evidence["post_quality_unity_validation"])
            reviewed = review(project_root=workspace, project_id=project_id, evidence=evidence)
            report = cast(GameValidatorAIResult, reviewed)
            record(f"audit_{attempt:02d}", report)
            if report.get("status") == "passed":
                return report
        except Exception as error:  # noqa: BLE001 - preserve the original audit and project
            previous_repair_error = f"{type(error).__name__}: {error}"
            record(f"repair_error_{attempt:02d}", {"error": previous_repair_error})
            report = cast(
                GameValidatorAIResult,
                {
                    **report,
                    "limitations": [
                        *report.get("limitations", []),
                        f"Quality repair {attempt} could not pass Unity: {previous_repair_error}",
                    ],
                },
            )
            continue
    return report


def _hard_failure_report(evidence: dict[str, Any]) -> GameValidatorAIResult:
    failed = [
        name
        for name, payload in evidence.items()
        if name.endswith("validation_result")
        and isinstance(payload, dict)
        and payload.get("status") not in {"passed", "skipped"}
    ]
    return {
        "report_version": "1.0.0",
        "contract_version": CONTRACT_VERSION,
        "status": "failed",
        "score": 0.0,
        "summary": "Hard validation failed, so the completed game is not eligible for AI approval.",
        "requirement_coverage": [
            {
                "requirement": "All deterministic and Unity validation gates must pass",
                "status": "missing",
                "evidence": failed or ["final_validation_result.status"],
            }
        ],
        "findings": [
            {
                "severity": "error",
                "category": "evidence",
                "message": "One or more mandatory validation stages failed.",
                "evidence": failed or ["final_validation_result.status"],
                "recommendation": "Resolve hard validation errors before requesting an AI quality audit.",
            }
        ],
        "strengths": [],
        "limitations": ["AI quality review was not run because hard validation failed."],
        "inspected_files": [],
        "provider": "none",
        "model": "none",
        "attempts": 0,
        "turns": 0,
        "tool_calls": [],
    }


def _disabled_report() -> GameValidatorAIResult:
    return {
        "report_version": "1.0.0",
        "contract_version": CONTRACT_VERSION,
        "status": "needs_revision",
        "score": 0.0,
        "summary": "Independent Game Validator AI is disabled by configuration.",
        "requirement_coverage": [
            {
                "requirement": "Independent AI quality evaluation",
                "status": "unverifiable",
                "evidence": ["MAINFLOW_GAME_VALIDATOR_ENABLED=false"],
            }
        ],
        "findings": [],
        "strengths": [],
        "limitations": ["No AI quality judgment was produced."],
        "inspected_files": [],
        "provider": "none",
        "model": "none",
        "attempts": 0,
        "turns": 0,
        "tool_calls": [],
    }


def _execution_failure_report(error: Exception) -> GameValidatorAIResult:
    return {
        "report_version": "1.0.0",
        "contract_version": CONTRACT_VERSION,
        "status": "failed",
        "score": 0.0,
        "summary": "Independent Game Validator AI could not complete.",
        "requirement_coverage": [
            {
                "requirement": "Independent AI quality evaluation",
                "status": "unverifiable",
                "evidence": [f"{type(error).__name__}: {error}"],
            }
        ],
        "findings": [
            {
                "severity": "error",
                "category": "evidence",
                "message": f"Validator execution failed: {type(error).__name__}: {error}",
                "evidence": ["game_quality_validator execution"],
                "recommendation": "Check the Validator AI provider, model, timeout, and MCP access.",
            }
        ],
        "strengths": [],
        "limitations": ["The completed project was not independently evaluated."],
        "inspected_files": [],
        "provider": "none",
        "model": "none",
        "attempts": 0,
        "turns": 0,
        "tool_calls": [],
    }

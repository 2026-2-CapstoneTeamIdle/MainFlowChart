"""Run an independent AI quality audit after all deterministic validation."""

from __future__ import annotations

import os
from typing import Any, cast

from game_pipeline import create_game_quality_validator_from_environment
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
        else:
            provider = os.environ.get("MAINFLOW_FEATURE_PROVIDER", "local").strip().lower()
            validator = create_game_quality_validator_from_environment(
                state["project_id"], provider=provider
            )
            ai_report = validator.evaluate(state["project_id"], evidence)
            report = cast(
                GameValidatorAIResult, {"contract_version": CONTRACT_VERSION, **ai_report}
            )
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

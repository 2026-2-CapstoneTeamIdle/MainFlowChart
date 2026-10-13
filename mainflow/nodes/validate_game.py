"""Validate the game-logic draft before asset-specific validation."""

from __future__ import annotations

import os
from typing import cast

from game_pipeline import UnityProjectValidator
from mainflow.ArtifactManager import ArtifactManager
from mainflow.contracts import (
    CONTRACT_VERSION,
    GameLogicDraft,
    GameValidationResult,
    LogicAnalysis,
    ParsedRequest,
    ValidateGameAgentInput,
    ValidateGameAgentOutput,
)
from mainflow.nodes._common import log


# Node 계약
# - 이전 Node: design_game_logic
# - 입력 State: project_id, parsed_request, logic_analysis,
#   game_logic_draft
# - 입력 파일: data/parsed_request.json,
#   data/logic_analysis.json, game/game_logic_draft.json
# - 출력 State: game_validation_result(ArtifactReference)
# - 출력 파일: validation/game_validation_result.json
# - 다음 Node: create_asset_validation_spec
def validate_game_node(
    state: ValidateGameAgentInput,
) -> ValidateGameAgentOutput:
    """Validate the draft game using temporary assets."""
    log("임시 에셋을 사용해 설계된 게임을 검증합니다.")

    manager = ArtifactManager()
    try:
        request = cast(ParsedRequest, manager.read_json(state["parsed_request"]))
        cast(LogicAnalysis, manager.read_json(state["logic_analysis"]))
        draft = cast(GameLogicDraft, manager.read_json(state["game_logic_draft"]))
    except (OSError, ValueError, TypeError, KeyError, UnicodeError) as error:
        result: GameValidationResult = {
            "contract_version": CONTRACT_VERSION,
            "status": "failed",
            "checks": [
                {
                    "criterion_id": "validation.input_artifacts",
                    "passed": False,
                    "message": f"Validation input artifact could not be read: {error}",
                }
            ],
            "issues": [
                {
                    "code": "VALIDATION_INPUT_ARTIFACT_INVALID",
                    "severity": "error",
                    "message": str(error),
                }
            ],
        }
        return _write_result(manager, state["project_id"], result)

    source_errors: list[str] = []
    for reference in draft["source_artifacts"]:
        try:
            manager.read_bytes(reference)
        except (OSError, ValueError, TypeError, KeyError, UnicodeError) as error:
            source_errors.append(f"{reference.get('artifact_id', 'unknown')}: {error}")

    mode = os.environ.get("MAINFLOW_UNITY_VALIDATION_MODE", "auto").lower()
    timeout_text = os.environ.get("MAINFLOW_UNITY_VALIDATION_TIMEOUT_SECONDS", "300")
    try:
        timeout_seconds = int(timeout_text)
        validator = UnityProjectValidator(
            mode=mode,  # type: ignore[arg-type]
            unity_editor=os.environ.get("UNITY_EDITOR_PATH"),
            timeout_seconds=timeout_seconds,
        )
        project_root = manager.ensure_project(state["project_id"]) / "game" / "unity_project"
        outcome = validator.validate(project_root, draft, request)
    except (TypeError, ValueError) as error:
        result = {
            "contract_version": CONTRACT_VERSION,
            "status": "failed",
            "checks": [
                {
                    "criterion_id": "validation.configuration",
                    "passed": False,
                    "message": str(error),
                }
            ],
            "issues": [
                {
                    "code": "VALIDATION_CONFIGURATION_INVALID",
                    "severity": "error",
                    "message": str(error),
                }
            ],
        }
        return _write_result(manager, state["project_id"], result)

    source_passed = not source_errors
    outcome.checks.insert(
        0,
        {
            "criterion_id": "validation.source_artifacts",
            "passed": source_passed,
            "message": (
                "All game source artifacts passed integrity checks"
                if source_passed
                else "Invalid source artifacts: " + "; ".join(source_errors)
            ),
        },
    )
    if source_errors:
        outcome.issues.insert(
            0,
            {
                "code": "GAME_SOURCE_ARTIFACT_INVALID",
                "severity": "error",
                "message": "; ".join(source_errors),
            },
        )

    if outcome.unity_log:
        log_reference = manager.write_text(
            state["project_id"],
            "validation",
            "unity_validation.log",
            outcome.unity_log,
            producer="validate_game",
        )
        for check in outcome.checks:
            if check["criterion_id"] == "unity.batchmode":
                check["message"] += f" (log: {log_reference['artifact_id']})"
                break

    status = outcome.status
    result = {
        "contract_version": CONTRACT_VERSION,
        "status": status,
        "checks": outcome.checks,
        "issues": outcome.issues,
    }
    return _write_result(manager, state["project_id"], result)


def _write_result(
    manager: ArtifactManager,
    project_id: str,
    result: GameValidationResult,
) -> ValidateGameAgentOutput:
    return {
        "game_validation_result": manager.write_json(
            project_id,
            "validation",
            "game_validation_result.json",
            result,
            producer="validate_game",
        )
    }

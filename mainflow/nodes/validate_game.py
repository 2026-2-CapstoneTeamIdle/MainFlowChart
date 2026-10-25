"""Validate the game-logic draft before asset-specific validation."""

from __future__ import annotations

import os
from pathlib import Path
from typing import cast

from game_pipeline import UnityProjectValidator
from game_pipeline.feature_checklist_validation import FeatureChecklistWorkflow
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

    generation_failed = draft["status"] == "failed"
    if generation_failed and draft["entry_scene"] is None:
        result = {
            "contract_version": CONTRACT_VERSION,
            "status": "failed",
            "checks": [
                {
                    "criterion_id": "game.generation",
                    "passed": False,
                    "message": "Game generation failed before Unity validation.",
                }
            ],
            "issues": [
                {
                    "code": "GAME_GENERATION_FAILED",
                    "severity": "error",
                    "message": "; ".join(draft["notes"]),
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
        outcome = validator.validate(
            project_root,
            draft,
            request,
            allow_failed_diagnostic=generation_failed,
        )
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
    except Exception as error:  # noqa: BLE001 - intentional workflow failure boundary
        # Unity process, filesystem, or adapter failures must not cancel the
        # independent image and sound branches.
        result = {
            "contract_version": CONTRACT_VERSION,
            "status": "failed",
            "checks": [
                {
                    "criterion_id": "unity.validation_execution",
                    "passed": False,
                    "message": f"Unity validation could not complete: {error}",
                }
            ],
            "issues": [
                {
                    "code": "UNITY_VALIDATION_EXECUTION_FAILED",
                    "severity": "error",
                    "message": f"{type(error).__name__}: {error}",
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

    if generation_failed:
        outcome.checks.insert(
            0,
            {
                "criterion_id": "game.generation",
                "passed": False,
                "message": (
                    "Requested feature generation failed; the diagnostic Unity project was "
                    "validated to collect compile and scene evidence."
                ),
            },
        )
        outcome.issues.insert(
            0,
            {
                "code": "GAME_GENERATION_FAILED",
                "severity": "error",
                "message": "; ".join(draft["notes"]),
            },
        )

    checklist_setting = os.environ.get("MAINFLOW_FEATURE_CHECKLIST_VALIDATION", "1")
    if (
        not generation_failed
        and outcome.status == "passed"
        and mode != "static"
        and checklist_setting == "1"
    ):
        required_version = validator._read_project_version(project_root)
        editor = validator.unity_editor or validator.find_unity_editor(required_version)
        if editor is None:
            outcome.checks.append(
                {
                    "criterion_id": "unity.feature_checklists",
                    "passed": False,
                    "message": "Unity Editor is required for feature checklist tests.",
                }
            )
            outcome.issues.append(
                {
                    "code": "FEATURE_CHECKLIST_EDITOR_NOT_FOUND",
                    "severity": "error",
                    "message": "Unity Test Framework could not start without a Unity Editor.",
                }
            )
        else:
            checklist_source = Path(
                os.environ.get(
                    "MAINFLOW_FEATURE_CHECKLIST_SOURCE",
                    str(Path(__file__).resolve().parents[2] / "docs"),
                )
            ).resolve()
            checklist_workflow = FeatureChecklistWorkflow(
                unity_editor=editor,
                timeout_seconds=timeout_seconds,
                max_retries=int(os.environ.get("MAINFLOW_FEATURE_CHECKLIST_RETRIES", "10")),
            )
            try:
                checklist_outcome = checklist_workflow.run(
                    project_root=project_root,
                    workspace_root=manager.ensure_project(state["project_id"]),
                    source_root=checklist_source,
                    compile_validation=lambda changed_root: validator.validate(
                        changed_root,
                        draft,
                        request,
                        allow_failed_diagnostic=False,
                    ),
                )
                outcome.unity_log += checklist_outcome.log
                for result_item in checklist_outcome.results:
                    outcome.checks.append(
                        {
                            "criterion_id": (f"feature_checklist.{result_item.feature_id.lower()}"),
                            "passed": result_item.status in {"passed", "skipped"},
                            "message": (
                                f"{result_item.feature_name}: {result_item.status} — "
                                f"{result_item.message}"
                            ),
                        }
                    )
                outcome.issues.extend(checklist_outcome.issues)
            except Exception as error:  # noqa: BLE001 - independent validation boundary
                outcome.checks.append(
                    {
                        "criterion_id": "unity.feature_checklists",
                        "passed": False,
                        "message": f"Feature checklist validation could not complete: {error}",
                    }
                )
                outcome.issues.append(
                    {
                        "code": "FEATURE_CHECKLIST_EXECUTION_FAILED",
                        "severity": "error",
                        "message": f"{type(error).__name__}: {error}",
                    }
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

    status = "failed" if generation_failed else outcome.status
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

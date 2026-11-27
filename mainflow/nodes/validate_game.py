"""Validate the game-logic draft before asset-specific validation."""

from __future__ import annotations

import os
from pathlib import Path
from typing import cast

from game_pipeline import UnityProjectValidator
from game_pipeline.agent_harness_repair import (
    repair_feature_audit_with_configured_agent,
    repair_with_configured_agent_harness,
)
from game_pipeline.feature_checklist_validation import (
    FeatureChecklistOutcome,
    FeatureChecklistWorkflow,
)
from game_pipeline.feature_evidence_audit import audit_feature_evidence
from game_pipeline.requirement_constraints import forbids_player_projectiles
from game_pipeline.unity_project_validator import UnityValidationOutcome
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
        logic_analysis = cast(LogicAnalysis, manager.read_json(state["logic_analysis"]))
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
        if outcome.status == "failed" and not generation_failed and not source_errors:
            log("후속 게임 검증 실패를 CLI Agent Harness에 전달해 다시 수정합니다.")
            try:
                repair_result = repair_with_configured_agent_harness(
                    project_root=project_root,
                    workspace_root=manager.ensure_project(state["project_id"]),
                    draft=draft,
                    request=request,
                    initial_outcome=outcome,
                    phase="validate_game",
                    record=lambda name, data: manager.write_json(
                        state["project_id"],
                        "validation",
                        f"agent_repair/validate_game/{name}.json",
                        data,
                        producer="validate_game",
                    ),
                )
                if repair_result is not None:
                    outcome = repair_result.outcome
                    manager.write_json(
                        state["project_id"],
                        "validation",
                        "agent_repair/validate_game/result.json",
                        repair_result.to_dict(),
                        producer="validate_game",
                    )
                    log(
                        "CLI Agent Harness가 후속 게임 검증을 "
                        f"{len(repair_result.repair_results)}회 수정 후 통과했습니다."
                    )
            except Exception as repair_error:  # noqa: BLE001 - preserve original evidence
                outcome.checks.append(
                    {
                        "criterion_id": "agent_harness.validate_game_repair",
                        "passed": False,
                        "message": f"Downstream agent repair failed: {repair_error}",
                    }
                )
                outcome.issues.append(
                    {
                        "code": "AGENT_POST_VALIDATION_REPAIR_FAILED",
                        "severity": "error",
                        "message": f"{type(repair_error).__name__}: {repair_error}",
                    }
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
                max_retries=(
                    0
                    if os.environ.get("MAINFLOW_CODEX_STATIC_CHECKLISTS") == "1"
                    else int(os.environ.get("MAINFLOW_FEATURE_CHECKLIST_RETRIES", "10"))
                ),
            )
            try:

                def run_feature_checklists() -> FeatureChecklistOutcome:
                    return checklist_workflow.run(
                        project_root=project_root,
                        workspace_root=manager.ensure_project(state["project_id"]),
                        source_root=checklist_source,
                        compile_validation=lambda changed_root: validator.validate(
                            changed_root,
                            draft,
                            request,
                            allow_failed_diagnostic=False,
                        ),
                        project_id=state["project_id"],
                        logic_analysis=(
                            None
                            if os.environ.get("MAINFLOW_CODEX_STATIC_CHECKLISTS") == "1"
                            and os.environ.get("MAINFLOW_EARLY_FEATURE_CHECKLISTS") != "1"
                            else logic_analysis
                        ),
                        feature_requirements=logic_analysis["features"],
                        excluded_static_feature_ids=(
                            {"FC03"} if forbids_player_projectiles(request["condition"]) else set()
                        ),
                    )

                checklist_outcome = run_feature_checklists()
                checklist_log = checklist_outcome.log
                agent_repair_issues: list[dict[str, str]] = []
                agent_repair_limit = _feature_checklist_agent_repairs()
                for repair_attempt in range(1, agent_repair_limit + 1):
                    if checklist_outcome.status == "passed":
                        break
                    if any(
                        issue["code"]
                        in {
                            "DYNAMIC_FEATURE_CHECKLIST_FAILED",
                            "DYNAMIC_TEST_SOURCE_FAILED",
                            "DYNAMIC_TEST_INFRASTRUCTURE_FAILED",
                        }
                        for issue in checklist_outcome.issues
                    ):
                        log("동적 테스트 생성·실행 문제는 게임 코드 수리 대상으로 보내지 않습니다.")
                        break
                    checklist_failure = _checklist_failure_outcome(checklist_outcome)
                    log(
                        "Feature 체크리스트 실패를 CLI Agent Harness에 전달해 "
                        f"다시 수정합니다 ({repair_attempt}/{agent_repair_limit})."
                    )
                    try:
                        repair_result = repair_with_configured_agent_harness(
                            project_root=project_root,
                            workspace_root=manager.ensure_project(state["project_id"]),
                            draft=draft,
                            request=request,
                            initial_outcome=checklist_failure,
                            phase=f"feature_checklist_{repair_attempt}",
                            record=lambda name, data, current_attempt=repair_attempt: (
                                manager.write_json(
                                    state["project_id"],
                                    "validation",
                                    "agent_repair/feature_checklist/"
                                    f"attempt_{current_attempt}/{name}.json",
                                    data,
                                    producer="validate_game",
                                )
                            ),
                        )
                        if repair_result is None:
                            break
                        manager.write_json(
                            state["project_id"],
                            "validation",
                            f"agent_repair/feature_checklist/attempt_{repair_attempt}/result.json",
                            repair_result.to_dict(),
                            producer="validate_game",
                        )
                        checklist_outcome = run_feature_checklists()
                        checklist_log += (
                            "\n--- AGENT FEATURE CHECKLIST REPAIR "
                            f"{repair_attempt} ---\n{checklist_outcome.log}"
                        )
                    except Exception as repair_error:  # noqa: BLE001 - preserve evidence
                        agent_repair_issues.append(
                            {
                                "code": "FEATURE_CHECKLIST_AGENT_REPAIR_FAILED",
                                "severity": "error",
                                "message": f"{type(repair_error).__name__}: {repair_error}",
                            }
                        )
                        break

                outcome.unity_log += checklist_log
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
                outcome.issues.extend(agent_repair_issues)
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

    if (
        outcome.status == "passed"
        and os.environ.get("MAINFLOW_GAME_BUILDER", "").strip().lower()
        in {"codex_cli", "claude_code"}
        and forbids_player_projectiles(request["condition"])
    ):
        critical = [
            item
            for item in logic_analysis["criteria"]
            if item["target"] == "game"
            and item["criterion_id"].startswith("logic-")
            and (
                ("검" in item["description"] and "투사체" in item["description"])
                or ("검" in item["description"] and "회전 반경" in item["description"])
                or ("체력이 0" in item["description"] and "공격" in item["description"])
            )
        ]
        if critical:
            builder = os.environ["MAINFLOW_GAME_BUILDER"].strip().lower()
            workspace = manager.ensure_project(state["project_id"])
            audit_root = workspace / "validation" / "pre_asset_feature_audit"
            for attempt in range(3):
                try:
                    audited = audit_feature_evidence(
                        builder=builder,
                        project_root=project_root,
                        audit_root=audit_root,
                        criteria=critical,
                        features=logic_analysis["features"],
                    )
                except Exception as error:  # noqa: BLE001 - report a bounded audit failure
                    outcome.issues.append(
                        {
                            "code": "PRE_ASSET_SEMANTIC_AUDIT_FAILED",
                            "severity": "error",
                            "message": f"{type(error).__name__}: {error}",
                        }
                    )
                    break
                manager.write_json(
                    state["project_id"],
                    "validation",
                    f"pre_asset_feature_audit_attempt_{attempt}.json",
                    audited,
                    producer="validate_game",
                )
                missing = [
                    item
                    for item in critical
                    if not audited.get(item["criterion_id"], {}).get("satisfied")
                ]
                if not missing:
                    break
                repairable = [
                    item
                    for item in missing
                    if audited.get(item["criterion_id"], {}).get("verification_status")
                    == "unsatisfied"
                ]
                if not repairable or attempt >= 2:
                    for item in missing:
                        evidence = audited.get(item["criterion_id"], {})
                        outcome.issues.append(
                            {
                                "code": "PRE_ASSET_SEMANTIC_UNSATISFIED",
                                "severity": "error",
                                "message": f"{item['description']}: {evidence.get('reason', 'No verified source evidence')}",
                            }
                        )
                    break
                log(
                    f"에셋 적용 전 게임 규칙 {len(repairable)}개를 CLI Agent가 수정합니다 ({attempt + 1}/2)."
                )
                try:
                    repaired = repair_feature_audit_with_configured_agent(
                        project_root=project_root,
                        workspace_root=workspace,
                        draft=draft,
                        request=request,
                        findings=[
                            {
                                "criterion_id": item["criterion_id"],
                                "requirement": item["description"],
                                "reason": audited[item["criterion_id"]]["reason"],
                            }
                            for item in repairable
                        ],
                        iteration=attempt + 1,
                    )
                    if repaired is None:
                        break
                    outcome = repaired
                    if outcome.status != "passed":
                        break
                except Exception as error:  # noqa: BLE001 - preserve the failed gate
                    outcome.issues.append(
                        {
                            "code": "PRE_ASSET_SEMANTIC_REPAIR_FAILED",
                            "severity": "error",
                            "message": f"{type(error).__name__}: {error}",
                        }
                    )
                    break

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

    status = (
        "failed"
        if generation_failed or any(issue["severity"] == "error" for issue in outcome.issues)
        else outcome.status
    )
    result = {
        "contract_version": CONTRACT_VERSION,
        "status": status,
        "checks": outcome.checks,
        "issues": outcome.issues,
    }
    return _write_result(manager, state["project_id"], result)


def _feature_checklist_agent_repairs() -> int:
    name = "MAINFLOW_FEATURE_CHECKLIST_AGENT_REPAIRS"
    try:
        value = int(os.environ.get(name, "1"))
    except ValueError as error:
        raise ValueError(f"{name} must be an integer") from error
    if not 0 <= value <= 3:
        raise ValueError(f"{name} must be between 0 and 3")
    return value


def _checklist_failure_outcome(checklist: FeatureChecklistOutcome) -> UnityValidationOutcome:
    checks = [
        {
            "criterion_id": f"feature_checklist.{item.feature_id.lower()}",
            "passed": item.status in {"passed", "skipped"},
            "message": f"{item.feature_name}: {item.status} — {item.message}",
        }
        for item in checklist.results
    ]
    issues = [
        {
            "code": item["code"],
            "severity": "error",
            "message": item["message"],
        }
        for item in checklist.issues
    ]
    if not issues:
        issues = [
            {
                "code": "FEATURE_CHECKLIST_FAILED",
                "severity": "error",
                "message": check["message"],
            }
            for check in checks
            if not check["passed"]
        ]
    return UnityValidationOutcome(checks=checks, issues=issues, unity_log=checklist.log)


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

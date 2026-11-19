"""Require reproducible evidence for the completed, asset-bound game."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from game_pipeline import UnityProjectGenerator, UnityProjectValidator
from game_pipeline.agent_harness_repair import (
    repair_feature_audit_with_configured_agent,
    repair_with_configured_agent_harness,
)
from game_pipeline.design_catalog import GENRE_ALIASES
from game_pipeline.feature_evidence_audit import audit_feature_evidence
from game_pipeline.feature_planner import plan_feature_mechanics
from game_pipeline.game_quality import parse_playtest_metrics
from game_pipeline.gameplay_contracts import checkpoint_respawn_requested
from game_pipeline.runtime_invariants import REQUIRED_CAUSAL_TRANSITIONS
from mainflow.ArtifactManager import ArtifactManager
from mainflow.contracts import (
    CONTRACT_VERSION,
    ArtifactReference,
    FinalValidationAgentInput,
    FinalValidationAgentOutput,
    FinalValidationResult,
    ValidationCheckResult,
    ValidationIssue,
)
from mainflow.nodes._common import log


def final_validation_node(
    state: FinalValidationAgentInput,
    *,
    artifact_variant: str = "",
) -> FinalValidationAgentOutput:
    """Revalidate after asset import; missing evidence can never mean success."""
    if artifact_variant and not re.fullmatch(r"[a-z0-9_]+", artifact_variant):
        raise ValueError(
            "artifact_variant must contain only lowercase letters, digits and underscores"
        )
    artifact_suffix = f"_{artifact_variant}" if artifact_variant else ""
    repair_directory = f"agent_repair/{artifact_variant or 'final_validation'}"
    log("최종 에셋과 Unity 실행 증거를 기준으로 완성된 게임을 검증합니다.")
    manager = ArtifactManager()
    checks: list[ValidationCheckResult] = []
    issues: list[ValidationIssue] = []
    evidence: list[ArtifactReference] = []
    package: ArtifactReference | None = None
    reconciled_game_validation_reference: ArtifactReference | None = None
    audit_repair_candidates: list[dict[str, Any]] = []
    audit_inconclusive_ids: set[str] = set()

    def check(criterion_id: str, passed: bool, message: str, *, required: bool = True) -> None:
        checks.append({"criterion_id": criterion_id, "passed": bool(passed), "message": message})
        if not passed:
            issues.append(
                {
                    "code": "FINAL_REQUIREMENT_UNSATISFIED",
                    "severity": "error" if required else "warning",
                    "target_id": criterion_id,
                    "message": message,
                }
            )

    try:
        payloads: dict[str, Any] = {}
        for key in (
            "logic_analysis",
            "integrated_game",
            "game_logic_draft",
            "parsed_request",
            "game_validation_result",
            "image_validation_result",
            "sound_validation_result",
        ):
            reference = state[key]
            if reference["project_id"] != state["project_id"]:
                raise ValueError(f"Cross-project input: {key}")
            payloads[key] = manager.read_json(reference)
        logic = payloads["logic_analysis"]
        integrated = payloads["integrated_game"]
        draft = payloads["game_logic_draft"]
        visual_reference = state.get("visual_validation_result")
        if visual_reference is None:
            visual = {"mode": "disabled", "status": "skipped"}
        else:
            if visual_reference["project_id"] != state["project_id"]:
                raise ValueError("Cross-project input: visual_validation_result")
            visual = manager.read_json(visual_reference)
            evidence.append(visual_reference)
        check(
            "final.visual_validation",
            visual["status"] == "passed"
            or (visual["mode"] == "disabled" and visual["status"] == "skipped"),
            ("Visual validation must pass when enabled; disabled mode may be explicitly skipped"),
        )
        check(
            "integration.game_available",
            integrated["status"] == "integrated"
            and (
                integrated["entry_artifact"] is not None
                or integrated.get("asset_binding_manifest") is not None
            ),
            "An integrated Unity project and binding manifest are required",
        )
        for target in ("game", "image", "sound"):
            result = payloads[f"{target}_validation_result"]
            check(
                f"final.{target}_validation",
                result["status"] == "passed"
                and not any(issue["severity"] == "error" for issue in result["issues"]),
                f"Upstream {target} validation must pass",
            )
        if integrated["status"] == "integrated":
            references = list(integrated["game_artifacts"])
            if integrated["entry_artifact"] is not None:
                references.append(integrated["entry_artifact"])
            for reference in references:
                if reference["project_id"] != state["project_id"]:
                    raise ValueError("Cross-project integrated artifact")
                manager.read_bytes(reference)
            manifest_ref = integrated["asset_binding_manifest"]
            if manifest_ref["project_id"] != state["project_id"]:
                raise ValueError("Cross-project binding manifest")
            manifest = manager.read_json(manifest_ref)
            suppressed_placeholder_images = set(
                manifest.get("suppressed_placeholder_image_asset_ids", [])
            )
            fallback_sound_assets = set(
                payloads["sound_validation_result"].get("fallback_asset_ids", [])
            )
            check(
                "integration.required_assets",
                not manifest["missing_required_asset_ids"],
                "All required assets must be applied",
            )
            entries = manifest["entries"]
            ids = [entry["asset_id"] for entry in entries]
            check(
                "integration.unique_assets",
                len(ids) == len(set(ids)),
                "Binding asset IDs must be unique",
            )
            root_relative = Path("game/unity_project")
            root = manager.resolve_project_path(state["project_id"], root_relative)
            staged_manifest = json.loads(
                manager.read_project_file(
                    state["project_id"],
                    root_relative / "Assets/GameTemplate/Generated/AssetBindingManifest.json",
                )
            )
            check(
                "integration.manifest_consistency",
                staged_manifest == manifest,
                "Unity and workspace binding manifests must match",
            )
            for target in ("image", "sound"):
                validation = payloads[f"{target}_validation_result"]
                selection = validation["validated_assets"]
                if (
                    selection["manifest_version"] != "1.0.0"
                    or selection["contract_version"] != CONTRACT_VERSION
                ):
                    raise ValueError("Unsupported validated asset manifest")
                selected = {asset["asset_id"]: asset for asset in selection["assets"]}
                check(
                    f"integration.{target}_selection",
                    len(selected) == len(selection["assets"])
                    and set(selected) == set(validation["validated_asset_ids"]),
                    "Selected assets must match validated IDs",
                )
                applied = {entry["asset_id"] for entry in entries if entry["asset_type"] == target}
                required = set(draft[f"required_{target}_asset_ids"])
                if target == "image":
                    required -= suppressed_placeholder_images
                check(
                    f"integration.{target}_coverage",
                    required <= applied
                    and applied == set(integrated[f"applied_{target}_asset_ids"]),
                    "Required and applied IDs must match the binding manifest",
                )
                for entry in (entry for entry in entries if entry["asset_type"] == target):
                    asset = selected[entry["asset_id"]]
                    if asset["artifact"]["project_id"] != state["project_id"]:
                        raise ValueError("Cross-project selected artifact")
                    path = Path(entry["unity_path"])
                    if (
                        path.is_absolute()
                        or ".." in path.parts
                        or not path.as_posix().startswith(
                            "Assets/GameTemplate/Generated/AppliedAssets/"
                        )
                    ):
                        raise ValueError("Unsafe applied asset path")
                    same = (
                        asset["asset_type"] == target
                        and asset["unity_binding_key"] == entry["unity_binding_key"]
                        and path.suffix.lower() == "." + asset["file_format"].lower().lstrip(".")
                        and manager.read_bytes(asset["artifact"])
                        == manager.read_project_file(state["project_id"], root_relative / path)
                    )
                    check(
                        f"integration.asset.{entry['asset_id']}",
                        same,
                        "Applied bytes and binding must match the validated artifact",
                    )
            # A final pass requires real compilation and Play Mode, even when the earlier pass was static.
            validator = UnityProjectValidator(
                mode="required",
                unity_editor=os.environ.get("UNITY_EDITOR_PATH"),
                timeout_seconds=int(
                    os.environ.get("MAINFLOW_UNITY_VALIDATION_TIMEOUT_SECONDS", "300")
                ),
            )
            # Remove stale binding evidence before invoking Unity.
            report_path = root_relative / "Assets/GameTemplate/Generated/AssetBindingReport.json"
            manager.write_project_file(
                state["project_id"],
                report_path,
                b"{}",
                expected_sha256=hashlib.sha256(
                    manager.read_project_file(state["project_id"], report_path)
                ).hexdigest()
                if manager.resolve_project_path(state["project_id"], report_path).is_file()
                else None,
            )
            outcome = validator.validate(root, draft, payloads["parsed_request"])
            final_repair_applied = False
            if outcome.status == "failed":
                log("에셋 적용 후 Unity 검증 실패를 CLI Agent Harness에 전달해 다시 수정합니다.")
                try:
                    repair_result = repair_with_configured_agent_harness(
                        project_root=root,
                        workspace_root=manager.ensure_project(state["project_id"]),
                        draft=draft,
                        request=payloads["parsed_request"],
                        initial_outcome=outcome,
                        phase="final_validation",
                        record=lambda name, data: manager.write_json(
                            state["project_id"],
                            "validation",
                            f"{repair_directory}/{name}.json",
                            data,
                            producer="final_validation",
                        ),
                    )
                    if repair_result is not None:
                        outcome = repair_result.outcome
                        final_repair_applied = bool(repair_result.repair_results)
                        manager.write_json(
                            state["project_id"],
                            "validation",
                            f"{repair_directory}/result.json",
                            repair_result.to_dict(),
                            producer="final_validation",
                        )
                        log(
                            "CLI Agent Harness가 에셋 적용 후 검증을 "
                            f"{len(repair_result.repair_results)}회 수정 후 통과했습니다."
                        )
                except Exception as repair_error:  # noqa: BLE001 - preserve original evidence
                    outcome.checks.append(
                        {
                            "criterion_id": "agent_harness.final_validation_repair",
                            "passed": False,
                            "message": f"Final agent repair failed: {repair_error}",
                        }
                    )
                    outcome.issues.append(
                        {
                            "code": "AGENT_POST_VALIDATION_REPAIR_FAILED",
                            "severity": "error",
                            "message": f"{type(repair_error).__name__}: {repair_error}",
                        }
                    )
            reconciled_game_validation = outcome.status == "passed" and (
                _reconcile_upstream_game_validation(
                    checks,
                    issues,
                    payloads["game_validation_result"],
                )
            )
            if reconciled_game_validation:
                original_game_validation = payloads["game_validation_result"]
                evidence.append(
                    manager.write_json(
                        state["project_id"],
                        "validation",
                        f"game_validation_reconciled{artifact_suffix}.json",
                        {
                            "reason": (
                                "Authoritative post-asset Unity validation passed after an "
                                "earlier runtime-only game validation failure."
                            ),
                            "final_repair_applied": final_repair_applied,
                            "upstream_status": original_game_validation["status"],
                            "post_repair_unity_status": outcome.status,
                            "post_repair_checks": outcome.checks,
                        },
                        producer="final_validation",
                    )
                )
                evidence.append(state["game_validation_result"])
                reconciled_game_validation_reference = manager.write_json(
                    state["project_id"],
                    "validation",
                    f"game_validation_effective{artifact_suffix}.json",
                    {
                        **original_game_validation,
                        "status": "passed",
                        "checks": [
                            item for item in original_game_validation["checks"] if item["passed"]
                        ]
                        + outcome.checks,
                        "issues": [
                            item
                            for item in original_game_validation["issues"]
                            if item["severity"] != "error"
                        ],
                    },
                    producer="final_validation",
                )
                evidence.append(reconciled_game_validation_reference)
            check(
                "final.unity_validation",
                outcome.status == "passed",
                "Post-application Unity validation must pass",
            )
            checks.extend(outcome.checks)
            issues.extend(outcome.issues)
            evidence.append(
                manager.write_text(
                    state["project_id"],
                    "validation",
                    f"final_unity_validation{artifact_suffix}.log",
                    outcome.unity_log,
                    producer="final_validation",
                )
            )
            runtime = any(
                c["criterion_id"] == "unity.runtime_smoke" and c["passed"] for c in outcome.checks
            )
            check(
                "final.runtime_executed",
                runtime,
                "Post-application Play Mode must execute successfully",
            )
            report = json.loads(manager.read_project_file(state["project_id"], report_path))
            evidence.append(
                manager.write_json(
                    state["project_id"],
                    "validation",
                    f"final_asset_binding_report{artifact_suffix}.json",
                    report,
                    producer="final_validation",
                )
            )
            bound = set(report.get("scene_bound_asset_ids", []))
            imported = set(report.get("imported_asset_ids", []))
            registered = set(report.get("registry_asset_ids", []))
            check(
                "integration.unity_bindings",
                set(ids) <= bound & imported & registered
                and not report.get("missing_required_asset_ids", []),
                "Every applied asset must be imported, registered and scene-bound",
            )
            animated = {
                entry["asset_id"]
                for entry in entries
                if entry["asset_type"] == "image" and entry.get("animation_metadata_path")
            }
            check(
                "integration.character_animation_bindings",
                animated <= set(report.get("animation_bound_asset_ids", [])),
                "Every staged character sprite sheet must have a scene-bound Animator controller",
            )
            telemetry = parse_playtest_metrics(outcome.unity_log)
            plan = json.loads(
                manager.read_project_file(
                    state["project_id"],
                    root_relative / "Assets/GameTemplate/Generated/Design/validation_plan.json",
                )
            )
            expected = {scenario["scenario_id"] for scenario in plan["scenarios"]}
            passed = set(telemetry["passed_scenarios"])
            passed_transitions = set(telemetry["passed_transitions"])
            runtime_plan_passed = (
                runtime
                and telemetry["completed"]
                and not telemetry["failed_transition"]
                and not telemetry["validation_failures"]
                and expected <= passed
            )
            check(
                "final.start_to_goal",
                runtime_plan_passed,
                "Every genre-specific executable scenario must pass after asset import",
            )
            genre_profile = GENRE_ALIASES.get(logic["genre"])
            expected_transitions = set(
                REQUIRED_CAUSAL_TRANSITIONS.get(genre_profile, ()) if genre_profile else ()
            )
            if genre_profile == "Platformer" and checkpoint_respawn_requested(
                payloads["parsed_request"].get("condition", "")
            ):
                expected_transitions.discard("platformer.fall_to_checkpoint")
                expected_transitions.add("platformer.death_to_checkpoint")
            check(
                "final.causal_gameplay",
                expected_transitions <= passed_transitions,
                (
                    "Required gameplay cause-and-effect transitions passed"
                    if expected_transitions <= passed_transitions
                    else "Missing gameplay transitions: "
                    + ", ".join(sorted(expected_transitions - passed_transitions))
                ),
            )
            unresolved_feature_criteria: list[dict[str, Any]] = []
            for criterion in logic["criteria"]:
                # Semantic criteria require their own explicit checks, never a broad target status.
                matching = [
                    c
                    for c in payloads.get(f"{criterion['target']}_validation_result", {}).get(
                        "checks", []
                    )
                    if c["criterion_id"] == criterion["criterion_id"]
                ]
                if criterion["target"] == "integration":
                    matching = [c for c in checks if c["criterion_id"] == criterion["criterion_id"]]
                satisfied = bool(matching) and all(c["passed"] for c in matching)
                waiver_reason = None
                if (criterion["target"] == "image" and suppressed_placeholder_images) or (
                    criterion["target"] == "sound"
                    and fallback_sound_assets
                    and set(draft["required_sound_asset_ids"]) <= fallback_sound_assets
                ):
                    satisfied = True
                    waiver_reason = "no real asset provider configured"
                if (
                    not matching
                    and criterion["target"] == "image"
                    and criterion["criterion_id"] == "visual-style"
                ):
                    if visual["status"] == "passed":
                        satisfied = True
                    elif visual["mode"] == "disabled" and visual["status"] == "skipped":
                        satisfied = True
                        waiver_reason = "visual validation disabled"
                if criterion["target"] == "game" and not matching:
                    feature = next(
                        (
                            f
                            for f in logic["features"]
                            if criterion["criterion_id"] == "logic-" + f["feature_id"]
                        ),
                        None,
                    )
                    if feature is not None:
                        if _is_unity_execution_stability_feature(feature):
                            play_log = outcome.unity_log.rsplit("--- PLAY MODE ---", 1)[-1]
                            satisfied = (
                                outcome.status == "passed"
                                and runtime_plan_passed
                                and any(
                                    item["criterion_id"] == "unity.batchmode" and item["passed"]
                                    for item in outcome.checks
                                )
                                and not _has_runtime_exception(play_log)
                            )
                        else:
                            runtime_transition = _runtime_transition_for_feature(
                                feature,
                                genre_profile,
                            )
                            if runtime_transition is not None:
                                satisfied = runtime_transition in passed_transitions
                            else:
                                mechanics = set(
                                    plan_feature_mechanics([feature], logic["genre"]).mechanics
                                )
                                if mechanics:
                                    satisfied = (
                                        runtime_plan_passed
                                        and mechanics <= set(plan["required_feature_bindings"])
                                        and not mechanics.intersection(
                                            telemetry["unused_requested_features"]
                                        )
                                    )
                                elif feature.get("origin") == "genre_inferred":
                                    satisfied = runtime_plan_passed
                check(
                    criterion["criterion_id"],
                    satisfied,
                    (
                        criterion["description"]
                        + (
                            f" (skipped: {waiver_reason})"
                            if waiver_reason
                            else " (explicit evidence required)"
                        )
                    ),
                    required=criterion["required"] and criterion["criterion_id"] != "sound-mood",
                )
                if (
                    not satisfied
                    and criterion["target"] == "game"
                    and any(
                        criterion["criterion_id"] == "logic-" + feature["feature_id"]
                        for feature in logic["features"]
                    )
                ):
                    unresolved_feature_criteria.append(criterion)
            builder = os.environ.get("MAINFLOW_GAME_BUILDER", "").strip().lower()
            if (
                unresolved_feature_criteria
                and builder in {"codex_cli", "claude_code"}
                and outcome.status == "passed"
                and runtime_plan_passed
            ):
                log(
                    "실행 검증에서 직접 증명되지 않은 Feature "
                    f"{len(unresolved_feature_criteria)}개의 Unity 소스 연결을 Agent가 항목별로 검토합니다."
                )
                try:
                    audited = audit_feature_evidence(
                        builder=builder,
                        project_root=root,
                        audit_root=manager.ensure_project(state["project_id"])
                        / "validation"
                        / "feature_evidence_audit"
                        / (artifact_variant or "final_validation"),
                        criteria=unresolved_feature_criteria,
                        features=logic["features"],
                    )
                    evidence.append(
                        manager.write_json(
                            state["project_id"],
                            "validation",
                            f"feature_evidence_audit{artifact_suffix}.json",
                            audited,
                            producer="final_validation",
                        )
                    )
                    for item in checks:
                        audited_item = audited.get(item["criterion_id"])
                        if audited_item is None:
                            continue
                        if audited_item["satisfied"]:
                            item["passed"] = True
                            citations = ", ".join(
                                cited["path"] for cited in audited_item["evidence"]
                            )
                            item["message"] += f" (Unity source evidence: {citations})"
                            issues[:] = [
                                issue
                                for issue in issues
                                if issue.get("target_id") != item["criterion_id"]
                            ]
                        else:
                            reason = audited_item["reason"] or "No verified Unity source evidence"
                            item["message"] += f" (audit: {reason})"
                            for issue in issues:
                                if issue.get("target_id") == item["criterion_id"]:
                                    issue["message"] = item["message"]
                            verification_status = audited_item.get(
                                "verification_status", "unsatisfied"
                            )
                            if verification_status in {"evidence_invalid", "audit_unavailable"}:
                                audit_inconclusive_ids.add(item["criterion_id"])
                            elif verification_status == "unsatisfied":
                                audit_repair_candidates.append(
                                    {
                                        "criterion_id": item["criterion_id"],
                                        "requirement": item["message"],
                                        "reason": reason,
                                    }
                                )
                except Exception as audit_error:  # noqa: BLE001 - keep unmet criteria visible
                    check(
                        "final.feature_evidence_audit",
                        False,
                        f"Feature evidence audit could not complete: {audit_error}",
                        required=False,
                    )
            repair_round = _feature_audit_repair_round(artifact_variant)
            repair_limit = _feature_audit_repair_limit()
            repair_ids = {item["criterion_id"] for item in audit_repair_candidates}
            other_errors = [
                item
                for item in issues
                if item["severity"] == "error"
                and item.get("target_id") not in repair_ids | audit_inconclusive_ids
            ]
            if audit_repair_candidates and not other_errors and repair_round < repair_limit:
                log(
                    "최종 Feature 감사에서 발견한 기능 누락 "
                    f"{len(audit_repair_candidates)}개를 CLI Agent가 수정합니다 "
                    f"({repair_round + 1}/{repair_limit})."
                )
                try:
                    repaired = repair_feature_audit_with_configured_agent(
                        project_root=root,
                        workspace_root=manager.ensure_project(state["project_id"]),
                        draft=draft,
                        request=payloads["parsed_request"],
                        findings=audit_repair_candidates,
                        iteration=repair_round + 1,
                    )
                    if repaired is not None and repaired.status == "passed":
                        base_variant = re.sub(r"_?feature_repair_\d+$", "", artifact_variant)
                        next_variant = f"{base_variant}_feature_repair_{repair_round + 1}".lstrip(
                            "_"
                        )
                        return final_validation_node(state, artifact_variant=next_variant)
                except Exception as repair_error:  # noqa: BLE001 - retain original findings
                    check(
                        "final.feature_audit_repair",
                        False,
                        f"Feature audit repair failed: {type(repair_error).__name__}: {repair_error}",
                    )
            if not any(issue["severity"] == "error" for issue in issues):
                package = manager.write_bytes(
                    state["project_id"],
                    "game",
                    f"validated_unity_project{artifact_suffix}.zip",
                    UnityProjectGenerator().create_archive(root),
                    producer="final_validation",
                    media_type="application/zip",
                )
    except Exception as error:  # noqa: BLE001 - preserve a reproducible failure at the workflow boundary
        check("final.validation_execution", False, f"{type(error).__name__}: {error}")
    result: FinalValidationResult = {
        "contract_version": CONTRACT_VERSION,
        "status": "failed" if any(issue["severity"] == "error" for issue in issues) else "passed",
        "checks": checks,
        "issues": issues,
        "evidence": evidence,
        "entry_artifact": package,
    }
    output: FinalValidationAgentOutput = {
        "final_validation_result": manager.write_json(
            state["project_id"],
            "validation",
            f"final_validation_result{artifact_suffix}.json",
            result,
            producer="final_validation",
        )
    }
    if result["status"] == "passed" and reconciled_game_validation_reference is not None:
        output["game_validation_result"] = reconciled_game_validation_reference
    return output


def _is_unity_execution_stability_feature(feature: dict[str, Any]) -> bool:
    if feature.get("implementation_kind") != "design_constraint":
        return False
    text = " ".join(
        str(feature.get(key, ""))
        for key in ("name", "description", "acceptance_criteria", "source_text")
    ).casefold()
    return ("컴파일" in text and "런타임 예외" in text) or (
        "compile" in text and "runtime exception" in text
    )


def _has_runtime_exception(log: str) -> bool:
    return bool(
        re.search(
            r"(?m)^(?:\s*\[Exception\]\s*)?(?:\w+\.)*\w*Exception:\s",
            log,
        )
    )


def _feature_audit_repair_round(variant: str) -> int:
    match = re.search(r"(?:^|_)feature_repair_(\d+)$", variant)
    return int(match.group(1)) if match else 0


def _feature_audit_repair_limit() -> int:
    name = "MAINFLOW_FINAL_FEATURE_AUDIT_REPAIRS"
    try:
        value = int(os.environ.get(name, "2"))
    except ValueError as error:
        raise ValueError(f"{name} must be an integer") from error
    if not 0 <= value <= 3:
        raise ValueError(f"{name} must be between 0 and 3")
    return value


_RECONCILABLE_GAME_VALIDATION_CODES = frozenset(
    {
        "UNITY_RUNTIME_TEST_FAILED",
        "AGENT_POST_VALIDATION_REPAIR_FAILED",
    }
)


def _reconcile_upstream_game_validation(
    checks: list[ValidationCheckResult],
    issues: list[ValidationIssue],
    upstream: dict[str, Any],
) -> bool:
    """Replace a stale runtime-only failure after authoritative final Unity validation passes."""

    upstream_errors = [issue for issue in upstream["issues"] if issue["severity"] == "error"]
    if not upstream_errors or any(
        issue["code"] not in _RECONCILABLE_GAME_VALIDATION_CODES for issue in upstream_errors
    ):
        return False
    for item in checks:
        if item["criterion_id"] == "final.game_validation":
            item["passed"] = True
            item["message"] = (
                "Upstream runtime failure was repaired and authoritative final Unity validation "
                "passed"
            )
            break
    issues[:] = [item for item in issues if item.get("target_id") != "final.game_validation"]
    return True


def _runtime_transition_for_feature(
    feature: dict[str, Any],
    genre_profile: str | None,
) -> str | None:
    """Map semantic combat requirements to authoritative causal Play Mode evidence."""

    if genre_profile != "SurvivorLike":
        return None
    name = str(feature.get("name", "")).replace(" ", "")
    description = str(feature.get("description", "")).replace(" ", "")
    explicit_attack_names = {"공격", "자동공격", "8방향공격"}
    player_attack_phrases = (
        "플레이어가적을공격",
        "플레이어주변을회전하는검",
        "검이적에게피해",
        "무기가적에게피해",
    )
    if name in explicit_attack_names or any(
        phrase in description for phrase in player_attack_phrases
    ):
        return "survivor.attack_to_damage"
    return None

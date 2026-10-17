"""Require reproducible evidence for the completed, asset-bound game."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from game_pipeline import UnityProjectGenerator, UnityProjectValidator
from game_pipeline.feature_planner import plan_feature_mechanics
from game_pipeline.game_quality import parse_playtest_metrics
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


def final_validation_node(state: FinalValidationAgentInput) -> FinalValidationAgentOutput:
    """Revalidate after asset import; missing evidence can never mean success."""
    log("최종 에셋과 Unity 실행 증거를 기준으로 완성된 게임을 검증합니다.")
    manager = ArtifactManager()
    checks: list[ValidationCheckResult] = []
    issues: list[ValidationIssue] = []
    evidence: list[ArtifactReference] = []
    package: ArtifactReference | None = None

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
        check(
            "integration.game_available",
            integrated["status"] == "integrated" and integrated["entry_artifact"] is not None,
            "An integrated game package is required",
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
            for reference in integrated["game_artifacts"] + [integrated["entry_artifact"]]:
                if reference["project_id"] != state["project_id"]:
                    raise ValueError("Cross-project integrated artifact")
                manager.read_bytes(reference)
            manifest_ref = integrated["asset_binding_manifest"]
            if manifest_ref["project_id"] != state["project_id"]:
                raise ValueError("Cross-project binding manifest")
            manifest = manager.read_json(manifest_ref)
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
                    "final_unity_validation.log",
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
                    "final_asset_binding_report.json",
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
            telemetry = parse_playtest_metrics(outcome.unity_log)
            plan = json.loads(
                manager.read_project_file(
                    state["project_id"],
                    root_relative / "Assets/GameTemplate/Generated/Design/validation_plan.json",
                )
            )
            expected = {scenario["scenario_id"] for scenario in plan["scenarios"]}
            passed = set(telemetry["passed_scenarios"])
            check(
                "final.start_to_goal",
                runtime
                and telemetry["completed"]
                and not telemetry["failed_transition"]
                and "start_to_goal" in passed
                and expected <= passed,
                "All planned scenarios, including start-to-goal, must pass after asset import",
            )
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
                        mechanics = set(plan_feature_mechanics([feature], logic["genre"]).mechanics)
                        satisfied = (
                            runtime
                            and "feature_binding" in passed
                            and bool(mechanics)
                            and mechanics <= set(plan["required_feature_bindings"])
                            and not mechanics.intersection(telemetry["unused_requested_features"])
                        )
                check(
                    criterion["criterion_id"],
                    satisfied,
                    criterion["description"] + " (explicit evidence required)",
                    required=criterion["required"],
                )
            if not any(issue["severity"] == "error" for issue in issues):
                package = manager.write_bytes(
                    state["project_id"],
                    "game",
                    "validated_unity_project.zip",
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
    return {
        "final_validation_result": manager.write_json(
            state["project_id"],
            "validation",
            "final_validation_result.json",
            result,
            producer="final_validation",
        )
    }

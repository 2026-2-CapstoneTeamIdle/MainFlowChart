"""Validate generated sound assets."""

from __future__ import annotations

from typing import cast

from mainflow.ArtifactManager import ArtifactManager
from mainflow.contracts import (
    CONTRACT_VERSION,
    AssetGenerationRequest,
    AssetValidationSpec,
    ParsedRequest,
    SoundDraft,
    SoundValidationResult,
    ValidateSoundAgentInput,
    ValidateSoundAgentOutput,
    ValidationCheckResult,
    ValidationIssue,
)
from mainflow.nodes._common import log
from sound_pipeline import plan_sound_assets
from sound_pipeline.validation import SOUND_CRITERIA, AssetQC, check_asset, mark_duplicates


# Node 계약
# - 이전 Node: generate_sound + create_asset_validation_spec (join)
# - 입력 State: project_id, parsed_request, sound_asset_request, sound_draft,
#   asset_validation_spec
# - 입력 파일: data/parsed_request.json, game/asset_requests/sound_asset_request.json,
#   generated/sounds/sound_draft.json, validation/asset_validation_spec.json
# - 출력 State: sound_validation_result(ArtifactReference)
# - 출력 파일: validation/sound_validation_result.json, validation/sound_profile.json,
#   generated/sounds/processed/<asset>.wav (G2 보정본)
# - 다음 Node: apply_assets_to_game (validate_image와 합류)
def validate_sound_node(
    state: ValidateSoundAgentInput,
) -> ValidateSoundAgentOutput:
    """Check generated sound artifacts against the shared asset criteria."""
    log("유저 입력 + 에셋 검증서를 바탕으로 사운드 에셋을 검증합니다.")

    manager = ArtifactManager()
    project_id = state["project_id"]
    parsed = cast(ParsedRequest, manager.read_json(state["parsed_request"]))
    request = cast(AssetGenerationRequest, manager.read_json(state["sound_asset_request"]))
    draft = cast(SoundDraft, manager.read_json(state["sound_draft"]))
    spec = cast(AssetValidationSpec, manager.read_json(state["asset_validation_spec"]))

    # Category/loop/required come from the same planner as generation, never from draft notes.
    plans = {plan.asset_id: plan for plan in plan_sound_assets(request, parsed)}
    criteria = spec["sound_criteria"] or [
        {"criterion_id": cid, "target": "sound", "description": text, "required": required}
        for cid, text, required in SOUND_CRITERIA
    ]
    required_by_id = {c["criterion_id"]: c["required"] for c in criteria}

    issues: list[ValidationIssue] = []
    results: list[AssetQC] = []
    audio_by_id: dict[str, bytes] = {}
    processed: dict[str, str] = {}
    selected = {}
    for asset in draft["assets"]:
        plan = plans.get(asset["asset_id"])
        if plan is None:
            issues.append(
                {
                    "code": "sound-unrequested-asset",
                    "severity": "warning",
                    "message": "요청 목록에 없는 사운드 에셋입니다.",
                    "target_id": asset["asset_id"],
                }
            )
            continue
        audio = manager.read_bytes(asset["artifact"])
        audio_by_id[plan.asset_id] = audio
        qc = check_asset(
            audio,
            asset["file_format"],
            plan,
            required_by_id,
            placeholder=asset.get("provider") == "procedural",
        )
        if asset["unity_binding_key"] != next(
            item["unity_binding_key"]
            for item in request["assets"]
            if item["asset_id"] == plan.asset_id
        ):
            qc.decision = "REGENERATE"
            qc.failed.append("sound-binding-key")
        results.append(qc)
        selected[plan.asset_id] = {
            "asset_id": plan.asset_id,
            "asset_type": "sound",
            "unity_binding_key": asset["unity_binding_key"],
            "artifact": asset["artifact"],
            "file_format": asset["file_format"],
        }
        if qc.processed_wav is not None:
            reference = manager.write_bytes(
                project_id,
                "sound",
                f"processed/{plan.file_stem}.wav",
                qc.processed_wav,
                producer="validate_sound",
                media_type="audio/wav",
            )
            processed[plan.asset_id] = reference["relative_path"]
            selected[plan.asset_id]["artifact"] = reference
            selected[plan.asset_id]["file_format"] = "wav"
    mark_duplicates(results, audio_by_id, required_by_id)

    generated_ids = {qc.asset_id for qc in results}
    missing_required = False
    for plan in plans.values():
        if plan.asset_id not in generated_ids:
            missing_required |= plan.required
            issues.append(
                {
                    "code": "sound-missing-asset",
                    "severity": "error" if plan.required else "warning",
                    "message": "요청된 사운드 에셋이 생성되지 않았습니다.",
                    "target_id": plan.asset_id,
                }
            )
    for qc in results:
        for criterion in qc.failed:
            issues.append(
                {
                    "code": criterion,
                    "severity": "error"
                    if required_by_id.get(criterion) and qc.required
                    else "warning",
                    "message": f"{qc.decision}: {qc.error or criterion} 기준을 통과하지 못했습니다.",
                    "target_id": qc.asset_id,
                }
            )
        if qc.applied_fixes:
            issues.append(
                {
                    "code": "sound-dsp-fixed",
                    "severity": "info",
                    "message": "자동 보정: " + ", ".join(qc.applied_fixes),
                    "target_id": qc.asset_id,
                }
            )

    decisions = {qc.decision for qc in results}
    if missing_required:
        status = "failed"
    elif decisions & {"REGENERATE", "REVIEW"}:
        status = "needs_revision"
    else:
        status = "passed"

    checks: list[ValidationCheckResult] = []
    for criterion in criteria:
        failing = [qc.asset_id for qc in results if criterion["criterion_id"] in qc.failed]
        checks.append(
            {
                "criterion_id": criterion["criterion_id"],
                "passed": not failing,
                "message": "실패: " + ", ".join(failing) if failing else "통과",
            }
        )
    result: SoundValidationResult = {
        "contract_version": CONTRACT_VERSION,
        "status": status,
        "checks": checks,
        "issues": issues,
        "validated_asset_ids": [qc.asset_id for qc in results if qc.decision in ("PASS", "FIX")],
    }
    result["validated_assets"] = {
        "manifest_version": "1.0.0",
        "contract_version": CONTRACT_VERSION,
        "assets": [selected[asset_id] for asset_id in result["validated_asset_ids"]],
    }
    profile = {
        "contract_version": CONTRACT_VERSION,
        "assets": [
            {
                "asset_id": qc.asset_id,
                "category": qc.category,
                "required": qc.required,
                "decision": qc.decision,
                "failed": qc.failed,
                "error": qc.error,
                "metrics": qc.metrics,
                "applied_fixes": qc.applied_fixes,
                "processed_path": processed.get(qc.asset_id),
            }
            for qc in results
        ],
    }
    manager.write_json(
        project_id, "validation", "sound_profile.json", profile, producer="validate_sound"
    )
    log(f"사운드 검증 {status}: " + ", ".join(f"{qc.asset_id}={qc.decision}" for qc in results))
    return {
        "sound_validation_result": manager.write_json(
            project_id,
            "validation",
            "sound_validation_result.json",
            result,
            producer="validate_sound",
        )
    }

"""Validate generated image assets."""

from __future__ import annotations

from typing import cast

from mainflow.ArtifactManager import ArtifactManager
from mainflow.contracts import (
    CONTRACT_VERSION,
    AssetGenerationRequest,
    AssetValidationSpec,
    ImageDraft,
    ImageValidationResult,
    ParsedRequest,
    ValidateImageAgentInput,
    ValidateImageAgentOutput,
    ValidationCheckResult,
    ValidationIssue,
)
from mainflow.image_generation import (
    MISSING_REQUIRED_NOTE_PREFIX,
    SPRITE_SHEET_NOTE_PREFIX,
    TRANSPARENT_PROMPT,
    inspect_png,
)
from mainflow.image_spritesheet import validate_sheet
from mainflow.nodes._common import log


# Node 계약
# - 이전 Node: generate_image + create_asset_validation_spec (join)
# - 입력 State: project_id, parsed_request, image_asset_request, image_draft,
#   asset_validation_spec
# - 입력 파일: data/parsed_request.json, game/asset_requests/image_asset_request.json,
#   generated/images/image_draft.json, validation/asset_validation_spec.json
# - 출력 State: image_validation_result(ArtifactReference)
# - 출력 파일: validation/image_validation_result.json
# - 다음 Node: apply_assets_to_game (validate_sound와 합류)
def validate_image_node(
    state: ValidateImageAgentInput,
) -> ValidateImageAgentOutput:
    """Check generated image artifacts against the shared asset criteria."""
    log("유저 입력 + 에셋 검증서를 바탕으로 이미지 에셋을 검증합니다.")

    manager = ArtifactManager()
    cast(ParsedRequest, manager.read_json(state["parsed_request"]))
    draft = cast(ImageDraft, manager.read_json(state["image_draft"]))
    request = cast(
        AssetGenerationRequest,
        manager.read_json(state["image_asset_request"]),
    )
    spec = cast(AssetValidationSpec, manager.read_json(state["asset_validation_spec"]))

    # TODO: 비전 모델을 이용한 스타일 일치 검증 추가
    issues: list[ValidationIssue] = []
    generated_ids = {asset["asset_id"] for asset in draft["assets"]}
    requested_assets = {item["asset_id"]: item for item in request["assets"]}
    missing_ids = sorted(
        {
            item["asset_id"]
            for item in request["assets"]
            if item["required"] and item["asset_id"] not in generated_ids
        }
        | set(draft["missing_required_asset_ids"])
    )
    for asset_id in missing_ids:
        issues.append(
            {
                "code": "image-plan-complete",
                "severity": "error",
                "message": "필수 이미지 에셋이 생성되지 않았습니다.",
                "target_id": asset_id,
            }
        )

    sheet_errors = _check_sprite_sheets(manager, state["project_id"], draft["notes"])

    failed: dict[str, set[str]] = {}
    validated_asset_ids: list[str] = []
    for asset in draft["assets"]:
        asset_id = asset["asset_id"]
        errors: list[tuple[str, str]] = list(sheet_errors.get(asset_id, []))
        requested = requested_assets.get(asset_id)
        if requested is None:
            errors.append(("image-plan-complete", "요청에 없는 이미지 에셋입니다."))
        else:
            generation_spec = requested["generation_spec"]
            if asset["unity_binding_key"] != requested["unity_binding_key"]:
                errors.append(("image-plan-complete", "Unity 바인딩 키가 요청과 다릅니다."))
            if asset["kind"] != generation_spec["kind"]:
                errors.append(("image-plan-complete", "이미지 종류가 요청과 다릅니다."))
            expected_size = generation_spec.get("width"), generation_spec.get("height")
            if (asset["width"], asset["height"]) != expected_size:
                errors.append(
                    (
                        "image-size-match",
                        (
                            f"요청 {expected_size[0]}x{expected_size[1]}, "
                            f"결과 {asset['width']}x{asset['height']}"
                        ),
                    )
                )
        try:
            info = inspect_png(manager.read_bytes(asset["artifact"]))
        except (OSError, ValueError) as error:
            errors.append(("image-file-valid", f"PNG를 읽을 수 없습니다: {error}"))
        else:
            if (info.width, info.height) != (asset["width"], asset["height"]):
                errors.append(
                    (
                        "image-size-match",
                        f"선언 {asset['width']}x{asset['height']}, 실제 {info.width}x{info.height}",
                    )
                )
            requires_transparency = bool(
                requested and requested["generation_spec"].get("transparent", False)
            )
            if requires_transparency and not info.has_transparent_pixel:
                errors.append(("image-transparency", "투명 배경이 필요한 에셋입니다."))
        for code, message in errors:
            failed.setdefault(code, set()).add(asset_id)
            issues.append(
                {
                    "code": code,
                    "severity": "error",
                    "message": message,
                    "target_id": asset_id,
                }
            )
        if not errors:
            validated_asset_ids.append(asset_id)

    checks: list[ValidationCheckResult] = []
    for criterion in spec["image_criteria"]:
        criterion_id = criterion["criterion_id"]
        if criterion_id == "image-plan-complete":
            passed = not missing_ids
        else:
            passed = criterion_id not in failed
        checks.append(
            {
                "criterion_id": criterion_id,
                "passed": passed,
                "message": "통과" if passed else "실패 - issues 참고",
            }
        )

    required_ids = {
        criterion["criterion_id"] for criterion in spec["image_criteria"] if criterion["required"]
    }
    all_required_passed = all(
        check["passed"] for check in checks if check["criterion_id"] in required_ids
    )
    status = "passed" if draft["status"] == "generated" and all_required_passed else "failed"
    log(f"  - 이미지 검증 {status} ({len(validated_asset_ids)}/{len(draft['assets'])} 에셋 통과)")
    result: ImageValidationResult = {
        "contract_version": CONTRACT_VERSION,
        "status": status,
        "checks": checks,
        "issues": issues,
        "validated_asset_ids": validated_asset_ids,
    }
    return {
        "image_validation_result": manager.write_json(
            state["project_id"],
            "validation",
            "image_validation_result.json",
            result,
            producer="validate_image",
        )
    }


def _check_sprite_sheets(
    manager: ArtifactManager,
    project_id: str,
    notes: list[str],
) -> dict[str, list[tuple[str, str]]]:
    """Validate each sprite sheet recorded by generate_image, keyed by asset_id."""

    errors: dict[str, list[tuple[str, str]]] = {}
    for note in notes:
        if not note.startswith(SPRITE_SHEET_NOTE_PREFIX):
            continue
        asset_id, _, artifact_ids = note.removeprefix(SPRITE_SHEET_NOTE_PREFIX).partition("=")
        try:
            sheet_id, metadata_id = artifact_ids.split(",")
            sheet = manager.read_bytes(manager.get_artifact(project_id, sheet_id))
            metadata = manager.read_json(manager.get_artifact(project_id, metadata_id))
            problems = validate_sheet(sheet, metadata)
        except (KeyError, OSError, ValueError) as error:
            problems = [("image-sprite-sheet", f"스프라이트 시트를 읽을 수 없습니다: {error}")]
        if problems:
            errors.setdefault(asset_id, []).extend(problems)
    return errors

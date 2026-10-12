"""Validate generated image assets."""

from __future__ import annotations

from typing import cast

from mainflow.ArtifactManager import ArtifactManager
from mainflow.contracts import (
    CONTRACT_VERSION,
    AssetValidationSpec,
    ImageDraft,
    ImageValidationResult,
    ParsedRequest,
    ValidateImageAgentInput,
    ValidateImageAgentOutput,
)
from mainflow.nodes._common import log


# Node 계약
# - 이전 Node: generate_image + create_asset_validation_spec (join)
# - 입력 State: project_id, parsed_request, image_draft, asset_validation_spec
# - 입력 파일: data/parsed_request.json,
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
    cast(ImageDraft, manager.read_json(state["image_draft"]))
    cast(AssetValidationSpec, manager.read_json(state["asset_validation_spec"]))

    # TODO: 이미지 검증
    result: ImageValidationResult = {
        "contract_version": CONTRACT_VERSION,
        "status": "pending",
        "checks": [],
        "issues": [],
        "validated_asset_ids": [],
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

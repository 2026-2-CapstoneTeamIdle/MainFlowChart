"""Validate generated sound assets."""

from __future__ import annotations

from typing import cast

from mainflow.ArtifactManager import ArtifactManager
from mainflow.contracts import (
    CONTRACT_VERSION,
    AssetValidationSpec,
    ParsedRequest,
    SoundDraft,
    SoundValidationResult,
    ValidateSoundAgentInput,
    ValidateSoundAgentOutput,
)
from mainflow.nodes._common import log


# Node 계약
# - 이전 Node: generate_sound + create_asset_validation_spec (join)
# - 입력 State: project_id, parsed_request, sound_draft, asset_validation_spec
# - 입력 파일: data/parsed_request.json,
#   generated/sounds/sound_draft.json, validation/asset_validation_spec.json
# - 출력 State: sound_validation_result(ArtifactReference)
# - 출력 파일: validation/sound_validation_result.json
# - 다음 Node: apply_assets_to_game (validate_image와 합류)
def validate_sound_node(
    state: ValidateSoundAgentInput,
) -> ValidateSoundAgentOutput:
    """Check generated sound artifacts against the shared asset criteria."""
    log("유저 입력 + 에셋 검증서를 바탕으로 사운드 에셋을 검증합니다.")

    manager = ArtifactManager()
    cast(ParsedRequest, manager.read_json(state["parsed_request"]))
    cast(SoundDraft, manager.read_json(state["sound_draft"]))
    cast(AssetValidationSpec, manager.read_json(state["asset_validation_spec"]))

    # TODO: 사운드 검증
    result: SoundValidationResult = {
        "contract_version": CONTRACT_VERSION,
        "status": "pending",
        "checks": [],
        "issues": [],
        "validated_asset_ids": [],
    }
    return {
        "sound_validation_result": manager.write_json(
            state["project_id"],
            "validation",
            "sound_validation_result.json",
            result,
            producer="validate_sound",
        )
    }

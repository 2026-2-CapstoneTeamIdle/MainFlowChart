"""Create image and sound validation criteria from game validation."""

from __future__ import annotations

from typing import cast

from mainflow.ArtifactManager import ArtifactManager
from mainflow.contracts import (
    CONTRACT_VERSION,
    AssetValidationSpec,
    AssetValidationSpecAgentInput,
    AssetValidationSpecAgentOutput,
    GameValidationResult,
    ParsedRequest,
)
from mainflow.image_generation import image_criteria
from mainflow.nodes._common import log
from sound_pipeline.validation import SOUND_CRITERIA


# Node 계약
# - 이전 Node: validate_game
# - 입력 State: project_id, parsed_request, game_validation_result
# - 입력 파일: data/parsed_request.json,
#   validation/game_validation_result.json
# - 출력 State: asset_validation_spec(ArtifactReference)
# - 출력 파일: validation/asset_validation_spec.json
# - 다음 Node: validate_image, validate_sound (각 생성 결과와 합류)
def create_asset_validation_spec_node(
    state: AssetValidationSpecAgentInput,
) -> AssetValidationSpecAgentOutput:
    """Derive asset-specific validation criteria from game validation."""
    log("게임 검증 결과를 바탕으로 이미지/사운드 에셋 검증서를 생성합니다.")

    manager = ArtifactManager()
    cast(ParsedRequest, manager.read_json(state["parsed_request"]))
    cast(
        GameValidationResult,
        manager.read_json(state["game_validation_result"]),
    )

    # TODO: game_validation_result를 이용해 실제 검증 기준 생성
    spec: AssetValidationSpec = {
        "contract_version": CONTRACT_VERSION,
        "spec_id": "asset-validation",
        "image_criteria": (),
        "sound_criteria": [
            {
                "criterion_id": criterion_id,
                "target": "sound",
                "description": description,
                "required": required,
            }
            for criterion_id, description, required in SOUND_CRITERIA
        ],
    }
    return {
        "asset_validation_spec": manager.write_json(
            state["project_id"],
            "validation",
            "asset_validation_spec.json",
            spec,
            producer="create_asset_validation_spec",
        )
    }

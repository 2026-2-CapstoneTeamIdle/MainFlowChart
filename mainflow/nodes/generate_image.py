"""Generate image assets for the requested game."""

from __future__ import annotations

from typing import cast

from mainflow.ArtifactManager import ArtifactManager
from mainflow.contracts import (
    CONTRACT_VERSION,
    GenerateImageAgentInput,
    GenerateImageAgentOutput,
    ImageDraft,
    InitialFinalValidationSpec,
    ParsedRequest,
)
from mainflow.nodes._common import log


# Node 계약
# - 이전 Node: create_initial_final_validation_spec
# - 입력 State: project_id, parsed_request, initial_final_validation_spec
# - 입력 파일: data/parsed_request.json,
#   validation/initial_final_validation_spec.json
# - 출력 State: image_draft(ArtifactReference)
# - 출력 파일: generated/images/image_draft.json 및 향후 이미지 에셋
# - 다음 Node: validate_image (asset_validation_spec과 합류)
def generate_image_node(
    state: GenerateImageAgentInput,
) -> GenerateImageAgentOutput:
    """Generate image artifacts and return their immutable draft reference."""
    log("이미지 에셋을 생성합니다. (현재는 뼈대만 실행)")

    manager = ArtifactManager()
    cast(ParsedRequest, manager.read_json(state["parsed_request"]))
    cast(
        InitialFinalValidationSpec,
        manager.read_json(state["initial_final_validation_spec"]),
    )

    # TODO: 실제 이미지 생성
    draft: ImageDraft = {
        "contract_version": CONTRACT_VERSION,
        "draft_id": "image-draft",
        "status": "pending",
        "assets": [],
        "notes": ["이미지 생성 Agent 구현 전 placeholder"],
    }
    return {
        "image_draft": manager.write_json(
            state["project_id"],
            "image",
            "image_draft.json",
            draft,
            producer="generate_image",
        )
    }

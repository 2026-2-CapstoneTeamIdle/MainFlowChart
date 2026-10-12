"""Create the initial final-validation specification."""

from __future__ import annotations

from typing import cast

from mainflow.ArtifactManager import ArtifactManager
from mainflow.contracts import (
    CONTRACT_VERSION,
    InitialFinalValidationSpec,
    InitialValidationSpecAgentInput,
    InitialValidationSpecAgentOutput,
    ParsedRequest,
)
from mainflow.nodes._common import log


# Node 계약
# - 이전 Node: parse_input
# - 입력 State: project_id, parsed_request(ArtifactReference)
# - 입력 파일: data/parsed_request.json
# - 출력 State: initial_final_validation_spec(ArtifactReference)
# - 출력 파일: validation/initial_final_validation_spec.json
# - 다음 Node: generate_image, design_game_logic, generate_sound (병렬)
def create_initial_final_validation_spec_node(
    state: InitialValidationSpecAgentInput,
) -> InitialValidationSpecAgentOutput:
    """Persist the criteria that the completed game must satisfy."""
    log("최종 검증에 사용할 최초 검증서를 생성합니다.")

    manager = ArtifactManager()
    cast(ParsedRequest, manager.read_json(state["parsed_request"]))

    # TODO: 실제 최종 검증 기준 작성
    spec: InitialFinalValidationSpec = {
        "contract_version": CONTRACT_VERSION,
        "spec_id": "initial-final-validation",
        "criteria": [],
    }
    return {
        "initial_final_validation_spec": manager.write_json(
            state["project_id"],
            "validation",
            "initial_final_validation_spec.json",
            spec,
            producer="create_initial_final_validation_spec",
        )
    }

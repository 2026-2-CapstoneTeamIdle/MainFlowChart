"""Parse initial input and create the project workspace."""

from __future__ import annotations

from mainflow.ArtifactManager import ArtifactManager
from mainflow.contracts import (
    CONTRACT_VERSION,
    ParseInputAgentInput,
    ParseInputAgentOutput,
    ParsedRequest,
)
from mainflow.nodes._common import log


# Node 계약
# - 이전 Node: user_input
# - 입력 State: image_style, genre, quality
# - 입력 파일: 없음
# - 출력 State: project_id, parsed_request(ArtifactReference)
# - 출력 파일: data/parsed_request.json
# - 다음 Node: create_initial_final_validation_spec
def parse_input_node(state: ParseInputAgentInput) -> ParseInputAgentOutput:
    """Normalize the request and persist it as the first project artifact."""
    log("유저 입력을 파싱합니다.")

    # TODO: 이후 AdviserAI / LLM을 이용한 실제 요구사항 파싱
    manager = ArtifactManager()
    project_id = manager.create_project()
    parsed_request: ParsedRequest = {
        "contract_version": CONTRACT_VERSION,
        "image_style": state["image_style"],
        "genre": state["genre"],
        "quality": state["quality"],
    }
    return {
        "project_id": project_id,
        "parsed_request": manager.write_json(
            project_id,
            "data",
            "parsed_request.json",
            parsed_request,
            producer="parse_input",
        ),
    }

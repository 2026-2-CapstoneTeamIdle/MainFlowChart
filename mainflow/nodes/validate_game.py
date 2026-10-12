"""Validate the game-logic draft before asset-specific validation."""

from __future__ import annotations

from typing import cast

from mainflow.ArtifactManager import ArtifactManager
from mainflow.contracts import (
    CONTRACT_VERSION,
    GameLogicDraft,
    GameValidationResult,
    LogicAnalysis,
    ParsedRequest,
    ValidateGameAgentInput,
    ValidateGameAgentOutput,
)
from mainflow.nodes._common import log


# Node 계약
# - 이전 Node: design_game_logic
# - 입력 State: project_id, parsed_request, logic_analysis,
#   game_logic_draft
# - 입력 파일: data/parsed_request.json,
#   data/logic_analysis.json, game/game_logic_draft.json
# - 출력 State: game_validation_result(ArtifactReference)
# - 출력 파일: validation/game_validation_result.json
# - 다음 Node: create_asset_validation_spec
def validate_game_node(
    state: ValidateGameAgentInput,
) -> ValidateGameAgentOutput:
    """Validate the draft game using temporary assets."""
    log("임시 에셋을 사용해 설계된 게임을 검증합니다.")

    manager = ArtifactManager()
    cast(ParsedRequest, manager.read_json(state["parsed_request"]))
    cast(LogicAnalysis, manager.read_json(state["logic_analysis"]))
    cast(GameLogicDraft, manager.read_json(state["game_logic_draft"]))

    # TODO: Unity Test Framework / build / logic validation
    result: GameValidationResult = {
        "contract_version": CONTRACT_VERSION,
        "status": "pending",
        "checks": [],
        "issues": [],
    }
    return {
        "game_validation_result": manager.write_json(
            state["project_id"],
            "validation",
            "game_validation_result.json",
            result,
            producer="validate_game",
        )
    }

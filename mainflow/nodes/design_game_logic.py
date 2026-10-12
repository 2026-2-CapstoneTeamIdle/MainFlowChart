"""Design the game logic before generated assets are applied."""

from __future__ import annotations

from typing import cast

from mainflow.ArtifactManager import ArtifactManager
from mainflow.contracts import (
    CONTRACT_VERSION,
    DesignGameLogicAgentInput,
    DesignGameLogicAgentOutput,
    GameLogicDraft,
    InitialFinalValidationSpec,
    ParsedRequest,
)
from mainflow.nodes._common import log


# Node 계약
# - 이전 Node: create_initial_final_validation_spec
# - 입력 State: project_id, parsed_request, initial_final_validation_spec
# - 입력 파일: data/parsed_request.json,
#   validation/initial_final_validation_spec.json
# - 출력 State: game_logic_draft(ArtifactReference)
# - 출력 파일: game/game_logic_draft.json 및 향후 Unity 게임 파일
# - 다음 Node: validate_game
def design_game_logic_node(
    state: DesignGameLogicAgentInput,
) -> DesignGameLogicAgentOutput:
    """Create a game-logic draft using temporary asset assumptions."""
    log("게임 로직을 설계합니다. (이미지/사운드는 임시 에셋으로 가정)")

    manager = ArtifactManager()
    cast(ParsedRequest, manager.read_json(state["parsed_request"]))
    cast(
        InitialFinalValidationSpec,
        manager.read_json(state["initial_final_validation_spec"]),
    )

    # TODO: 실제 게임 로직 / Unity / Godot 코드 설계
    draft: GameLogicDraft = {
        "contract_version": CONTRACT_VERSION,
        "draft_id": "game-logic-draft",
        "status": "pending",
        "engine": "TBD",
        "entry_scene": None,
        "source_artifacts": [],
        "required_image_asset_ids": [],
        "required_sound_asset_ids": [],
        "notes": ["게임 로직 설계 Agent 구현 전 placeholder"],
    }
    return {
        "game_logic_draft": manager.write_json(
            state["project_id"],
            "game",
            "game_logic_draft.json",
            draft,
            producer="design_game_logic",
        )
    }

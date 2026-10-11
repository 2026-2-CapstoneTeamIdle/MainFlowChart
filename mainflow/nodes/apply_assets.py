"""Apply validated image and sound assets to the game draft."""

from __future__ import annotations

from typing import cast

from mainflow.ArtifactManager import ArtifactManager
from mainflow.contracts import (
    CONTRACT_VERSION,
    ApplyAssetsAgentInput,
    ApplyAssetsAgentOutput,
    GameLogicDraft,
    ImageDraft,
    ImageValidationResult,
    IntegratedGame,
    SoundDraft,
    SoundValidationResult,
)
from mainflow.nodes._common import log


# Node 계약
# - 이전 Node: validate_image + validate_sound (join)
# - 입력 State: project_id, game_logic_draft, image_draft, sound_draft,
#   image_validation_result, sound_validation_result
# - 입력 파일: game/game_logic_draft.json,
#   generated/images/image_draft.json, generated/sounds/sound_draft.json,
#   validation/image_validation_result.json,
#   validation/sound_validation_result.json
# - 출력 State: integrated_game(ArtifactReference)
# - 출력 파일: game/integrated_game.json 및 향후 통합 Unity 프로젝트
# - 다음 Node: final_validation
def apply_assets_to_game_node(
    state: ApplyAssetsAgentInput,
) -> ApplyAssetsAgentOutput:
    """Integrate only validated assets into the game project."""
    log("검증을 통과한 이미지/사운드 에셋을 게임에 적용합니다.")

    manager = ArtifactManager()
    cast(GameLogicDraft, manager.read_json(state["game_logic_draft"]))
    cast(ImageDraft, manager.read_json(state["image_draft"]))
    cast(SoundDraft, manager.read_json(state["sound_draft"]))
    cast(
        ImageValidationResult,
        manager.read_json(state["image_validation_result"]),
    )
    cast(
        SoundValidationResult,
        manager.read_json(state["sound_validation_result"]),
    )

    # TODO: 실제 Unity/Godot 프로젝트에 에셋 적용
    integrated_game: IntegratedGame = {
        "contract_version": CONTRACT_VERSION,
        "status": "pending",
        "entry_artifact": None,
        "game_artifacts": [],
        "applied_image_asset_ids": [],
        "applied_sound_asset_ids": [],
        "notes": ["에셋 통합 Agent 구현 전 placeholder"],
    }
    return {
        "integrated_game": manager.write_json(
            state["project_id"],
            "game",
            "integrated_game.json",
            integrated_game,
            producer="apply_assets_to_game",
        )
    }

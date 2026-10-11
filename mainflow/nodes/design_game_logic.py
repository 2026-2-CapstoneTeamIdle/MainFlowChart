"""Design the game logic before generated assets are applied."""

from __future__ import annotations

from typing import cast

from mainflow.ArtifactManager import ArtifactManager
from mainflow.contracts import (
    CONTRACT_VERSION,
    AnalysisResult,
    DesignGameLogicAgentInput,
    DesignGameLogicAgentOutput,
    GameLogicDraft,
    LogicAnalysis,
    ParsedRequest,
)
from mainflow.nodes._common import log
from game_pipeline import build_game_logic_design, normalize_game_spec


# Node 계약
# - 이전 Node: logic_analysis
# - 입력 State: project_id, parsed_request, analysis, logic_analysis
# - 입력 파일: data/parsed_request.json, data/analysis.json, data/logic_analysis.json
# - 출력 State: game_logic_draft(ArtifactReference)
# - 출력 파일: game/game_logic_draft.json 및 향후 Unity 게임 파일
# - 다음 Node: validate_game
def design_game_logic_node(
    state: DesignGameLogicAgentInput,
) -> DesignGameLogicAgentOutput:
    """Create a game-logic draft using temporary asset assumptions."""
    log("게임 로직을 설계합니다. (이미지/사운드는 임시 에셋으로 가정)")

    manager = ArtifactManager()
    request = cast(ParsedRequest, manager.read_json(state["parsed_request"]))
    analysis = cast(AnalysisResult, manager.read_json(state["analysis"]))
    cast(LogicAnalysis, manager.read_json(state["logic_analysis"]))

    game_spec = normalize_game_spec(
        request["genre"],
        {
            "features": [
                {
                    "feature_id": feature["feature_id"],
                    "description": feature["description"],
                    "required": True,
                }
                for feature in analysis["features"]
            ]
        },
    )
    design = build_game_logic_design(game_spec)
    design_reference = manager.write_json(
        state["project_id"],
        "game",
        "game_logic_design.json",
        design,
        producer="design_game_logic",
    )
    image_asset_ids = [
        asset["asset_id"]
        for asset in game_spec["asset_requirements"]
        if asset["asset_type"] == "image"
    ]
    sound_asset_ids = [
        asset["asset_id"]
        for asset in game_spec["asset_requirements"]
        if asset["asset_type"] == "sound"
    ]
    notes = [
        f"{game_spec['genre']} 프리셋과 공통 모듈을 조합한 Unity 설계 초안",
        "Unity 프로젝트 파일 생성은 후속 generator 구현에서 수행",
    ]
    if design["unsupported_mechanics"]:
        notes.append(
            "별도 구현이 필요한 mechanic: "
            + ", ".join(design["unsupported_mechanics"])
        )

    draft: GameLogicDraft = {
        "contract_version": CONTRACT_VERSION,
        "draft_id": f"{game_spec['genre'].lower()}-game-logic-draft",
        "status": "generated",
        "engine": "Unity",
        "entry_scene": None,
        "source_artifacts": [design_reference],
        "required_image_asset_ids": image_asset_ids,
        "required_sound_asset_ids": sound_asset_ids,
        "notes": notes,
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

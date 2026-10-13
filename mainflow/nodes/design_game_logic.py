"""Design the game logic before generated assets are applied."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from game_pipeline import (
    UnityProjectGenerator,
    build_game_logic_design,
    normalize_game_spec,
)
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


# Node 계약
# - 이전 Node: logic_analysis
# - 입력 State: project_id, parsed_request, analysis, logic_analysis
# - 입력 파일: data/parsed_request.json, data/analysis.json, data/logic_analysis.json
# - 출력 State: game_logic_draft, image_asset_request, sound_asset_request
# - 출력 파일: game/game_logic_draft.json, game/asset_requests/*.json,
#   game/unity_project/, game/unity_project.zip
# - 다음 Node: validate_game, generate_image, generate_sound
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
            "viewpoint": request["viewpoint"],
            "features": [
                {
                    "feature_id": feature["feature_id"],
                    "description": feature["description"],
                    "required": True,
                }
                for feature in analysis["features"]
            ],
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
    workspace_project_root = manager.ensure_project(state["project_id"])
    unity_project_root = workspace_project_root / "game" / "unity_project"
    generator = UnityProjectGenerator()
    generation = generator.generate(
        design,
        unity_project_root,
        image_style=request["image_style"],
        mood_style=request["mood_style"],
        viewpoint=request["viewpoint"],
        reference_image=request["custom_image"],
    )
    manifest_reference = manager.import_file(
        state["project_id"],
        "game",
        generation.manifest_path,
        producer="design_game_logic",
        filename="unity_project_manifest.json",
        media_type="application/json",
    )
    archive_reference = manager.write_bytes(
        state["project_id"],
        "game",
        "unity_project.zip",
        generator.create_archive(generation.project_root),
        producer="design_game_logic",
        media_type="application/zip",
    )
    image_request_reference = manager.import_file(
        state["project_id"],
        "game",
        generation.image_asset_request_path,
        producer="design_game_logic",
        filename="asset_requests/image_asset_request.json",
        media_type="application/json",
    )
    sound_request_reference = manager.import_file(
        state["project_id"],
        "game",
        generation.sound_asset_request_path,
        producer="design_game_logic",
        filename="asset_requests/sound_asset_request.json",
        media_type="application/json",
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
        "Unity 프로젝트와 배포용 ZIP 생성 완료",
        "Unity에서 처음 열면 선택 모듈로 Bootstrap 씬을 자동 재구성",
    ]
    if design["unsupported_mechanics"]:
        notes.append("별도 구현이 필요한 mechanic: " + ", ".join(design["unsupported_mechanics"]))
    draft: GameLogicDraft = {
        "contract_version": CONTRACT_VERSION,
        "draft_id": f"{game_spec['genre'].lower()}-game-logic-draft",
        "status": "generated",
        "engine": "Unity",
        "entry_scene": str(
            Path(generation.entry_scene).relative_to(workspace_project_root).as_posix()
        ),
        "source_artifacts": [
            design_reference,
            manifest_reference,
            archive_reference,
            image_request_reference,
            sound_request_reference,
        ],
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
        ),
        "image_asset_request": image_request_reference,
        "sound_asset_request": sound_request_reference,
    }

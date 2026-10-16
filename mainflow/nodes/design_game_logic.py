"""Design the game logic before generated assets are applied."""

from __future__ import annotations

import os
from pathlib import Path
from typing import cast

from game_pipeline import (
    UnityProjectGenerator,
    attach_generated_modules,
    build_game_logic_design,
    create_feature_generator_from_environment,
    normalize_game_spec,
    plan_feature_mechanics,
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
from game_pipeline.feature_contract import build_feature_contract
from game_pipeline.repair_loop import validate_and_repair


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

    feature_plan = plan_feature_mechanics(analysis["features"], request["genre"])
    game_spec = normalize_game_spec(
        request["genre"],
        {
            "viewpoint": request["viewpoint"],
            "features": feature_plan.game_features,
            "mechanics": feature_plan.mechanics,
        },
    )
    design = build_game_logic_design(game_spec)
    unity_generator = UnityProjectGenerator()
    image_request = unity_generator.build_asset_request(
        design,
        "image",
        image_style=request["image_style"],
        mood_style=request["mood_style"],
        viewpoint=request["viewpoint"],
        reference_image=request["custom_image"],
    )
    sound_request = unity_generator.build_asset_request(
        design,
        "sound",
        image_style=request["image_style"],
        mood_style=request["mood_style"],
        viewpoint=request["viewpoint"],
        reference_image=None,
    )
    image_request_reference = manager.write_json(
        state["project_id"],
        "game",
        "asset_requests/image_asset_request.json",
        image_request,
        producer="design_game_logic",
    )
    sound_request_reference = manager.write_json(
        state["project_id"],
        "game",
        "asset_requests/sound_asset_request.json",
        sound_request,
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
    request_references = [image_request_reference, sound_request_reference]
    feature_provider = os.environ.get("MAINFLOW_FEATURE_PROVIDER", "local").strip().lower()
    try:
        if design["unsupported_mechanics"]:
            log(f"기존 모듈에 없는 기능을 {feature_provider} 모델로 생성합니다.")
            feature_generator = create_feature_generator_from_environment()
            generated_modules = feature_generator.generate(
                design,
                feature_plan.generation_requirements,
            )
            design = attach_generated_modules(design, generated_modules)

        design_reference = manager.write_json(
            state["project_id"],
            "game",
            "game_logic_design.json",
            design,
            producer="design_game_logic",
        )
        workspace_project_root = manager.ensure_project(state["project_id"])
        unity_project_root = workspace_project_root / "game" / "unity_project"
        generation = unity_generator.generate(
            design,
            unity_project_root,
            image_style=request["image_style"],
            mood_style=request["mood_style"],
            viewpoint=request["viewpoint"],
            reference_image=request["custom_image"],
        )
        if design["generated_modules"]:
            manager.write_json(
                state["project_id"],
                "game",
                "feature_code_contract.json",
                build_feature_contract(),
                producer="design_game_logic",
            )
            log("Unity 컴파일·Play Mode 검증 후 필요하면 생성 코드를 수정합니다.")
            design, generation = validate_and_repair(
                design=design,
                generation=generation,
                request=request,
                generator=unity_generator,
                feature_generator=feature_generator,
                max_repairs=int(os.environ.get("MAINFLOW_GAME_MAX_REPAIRS", "2")),
                record=lambda name, data: manager.write_json(
                    state["project_id"],
                    "validation",
                    f"repair/{name}.json",
                    data,
                    producer="design_game_logic",
                ),
            )
            design_reference = manager.write_json(
                state["project_id"],
                "game",
                "game_logic_design.json",
                design,
                producer="design_game_logic",
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
            unity_generator.create_archive(generation.project_root),
            producer="design_game_logic",
            media_type="application/zip",
        )
        notes = [
            f"{game_spec['genre']} 프리셋과 공통 모듈을 조합한 Unity 설계 초안",
            "Unity 프로젝트와 배포용 ZIP 생성 완료",
            "Unity에서 처음 열면 선택 모듈로 Bootstrap 씬을 자동 재구성",
        ]
        if design["generated_modules"]:
            notes.append(
                f"{feature_provider} 생성 모듈: "
                + ", ".join(module["module_id"] for module in design["generated_modules"])
            )
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
                *request_references,
            ],
            "required_image_asset_ids": image_asset_ids,
            "required_sound_asset_ids": sound_asset_ids,
            "notes": notes,
        }
    except Exception as error:  # noqa: BLE001 - intentional workflow failure boundary
        # This node is a fan-out boundary.  Record game failure as data instead
        # of aborting the graph so image and sound branches can still run.
        log(f"게임 생성에 실패했지만 이미지/사운드 파이프라인은 계속합니다: {error}")
        design_reference = manager.write_json(
            state["project_id"],
            "game",
            "failed_game_logic_design.json",
            design,
            producer="design_game_logic",
        )
        failure_reference = manager.write_json(
            state["project_id"],
            "validation",
            "game_generation_failure.json",
            {
                "contract_version": CONTRACT_VERSION,
                "status": "failed",
                "stage": "design_game_logic",
                "error_type": type(error).__name__,
                "message": str(error),
            },
            producer="design_game_logic",
        )
        draft = {
            "contract_version": CONTRACT_VERSION,
            "draft_id": f"{game_spec['genre'].lower()}-game-logic-draft",
            "status": "failed",
            "engine": "Unity",
            "entry_scene": None,
            "source_artifacts": [
                design_reference,
                failure_reference,
                *request_references,
            ],
            "required_image_asset_ids": image_asset_ids,
            "required_sound_asset_ids": sound_asset_ids,
            "notes": [
                "게임 생성 실패로 Unity 프로젝트를 완성하지 못했습니다.",
                f"{type(error).__name__}: {error}",
                "이미지/사운드 요청은 독립적으로 생성되어 후속 파이프라인을 계속합니다.",
            ],
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

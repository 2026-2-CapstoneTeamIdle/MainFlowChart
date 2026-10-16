"""Apply validated image and sound assets to the generated Unity project."""

from __future__ import annotations

from typing import cast

from game_pipeline import UnityAssetApplicator, UnityProjectGenerator
from mainflow.ArtifactManager import ArtifactManager
from mainflow.contracts import (
    CONTRACT_VERSION,
    ApplyAssetsAgentInput,
    ApplyAssetsAgentOutput,
    AssetGenerationRequest,
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
    game_draft = cast(GameLogicDraft, manager.read_json(state["game_logic_draft"]))
    image_request = cast(
        AssetGenerationRequest,
        manager.read_json(state["image_asset_request"]),
    )
    sound_request = cast(
        AssetGenerationRequest,
        manager.read_json(state["sound_asset_request"]),
    )
    image_draft = cast(ImageDraft, manager.read_json(state["image_draft"]))
    sound_draft = cast(SoundDraft, manager.read_json(state["sound_draft"]))
    image_validation = cast(
        ImageValidationResult,
        manager.read_json(state["image_validation_result"]),
    )
    sound_validation = cast(
        SoundValidationResult,
        manager.read_json(state["sound_validation_result"]),
    )

    # 사운드 파일은 sound_draft.assets[].artifact로 찾는다. 요청서의 suggested_filename은
    # 항상 .wav지만 ELEVENLABS_OUTPUT_FORMAT=mp3_*이면 실제 파일은 .mp3다.
    game_failed = game_draft["status"] == "failed"
    if game_failed:
        integrated_game: IntegratedGame = {
            "contract_version": CONTRACT_VERSION,
            "status": "failed",
            "entry_artifact": None,
            "game_artifacts": [],
            "applied_image_asset_ids": [],
            "applied_sound_asset_ids": [],
            "notes": [
                "게임 생성 실패로 에셋 적용은 건너뛰었지만 이미지/사운드 파이프라인은 완료됨"
            ],
        }
    else:
        application = UnityAssetApplicator(manager).apply(
            state["project_id"],
            image_request,
            sound_request,
            image_draft,
            sound_draft,
            image_validation,
            sound_validation,
        )
        manifest_reference = manager.write_json(
            state["project_id"],
            "game",
            "asset_binding_manifest.json",
            application.manifest,
            producer="apply_assets_to_game",
        )
        unity_project_root = manager.resolve_project_path(
            state["project_id"],
            UnityAssetApplicator.UNITY_PROJECT_ROOT,
        )
        archive_reference = manager.write_bytes(
            state["project_id"],
            "game",
            "integrated_unity_project.zip",
            UnityProjectGenerator().create_archive(unity_project_root),
            producer="apply_assets_to_game",
            media_type="application/zip",
        )
        notes = [
            "검증을 통과한 에셋을 Unity 프로젝트에 복사하고 바인딩 manifest를 생성함",
            "Unity Editor가 프로젝트를 열 때 importer 설정과 씬 바인딩을 적용함",
        ]
        notes.extend(application.manifest["warnings"])
        integrated_game = {
            "contract_version": CONTRACT_VERSION,
            "status": "integrated",
            "entry_artifact": archive_reference,
            "game_artifacts": [manifest_reference, archive_reference],
            "applied_image_asset_ids": application.applied_image_asset_ids,
            "applied_sound_asset_ids": application.applied_sound_asset_ids,
            "notes": notes,
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

"""Apply validated image and sound assets to the generated Unity project."""

from __future__ import annotations

import os
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
    SoundDraft,
    SoundValidationResult,
)
from mainflow.nodes._common import log

APPLY_IMAGE_ASSETS_ENVIRONMENT_KEY = "MAINFLOW_APPLY_IMAGE_ASSETS"


def image_application_enabled() -> bool:
    """Return whether generated images are applied to Unity (default: off)."""

    value = os.environ.get(APPLY_IMAGE_ASSETS_ENVIRONMENT_KEY, "off").strip().lower()
    return value in {"on", "true", "1", "yes"}


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
    exclude_placeholder_images = os.environ.get(
        "MAINFLOW_GAME_BUILDER", "pipeline"
    ).strip().lower() in {
        "codex",
        "codex-cli",
        "codex_cli",
        "claude",
        "claude-code",
        "claude_code",
    }
    # MAINFLOW_APPLY_IMAGE_ASSETS=on으로 켜기 전까지 이미지는 생성만 하고 Unity에 적용하지 않는다.
    skip_image_application = not image_application_enabled()
    if skip_image_application:
        log(
            "  - MAINFLOW_APPLY_IMAGE_ASSETS가 꺼져 있어 생성된 이미지는 "
            "generated/images에만 두고 Unity에 적용하지 않습니다."
        )
    elif exclude_placeholder_images and "generator=placeholder" in image_draft["notes"]:
        log("  - 실제 이미지 백엔드가 없어 placeholder 이미지는 Unity에 적용하지 않습니다.")
    try:
        application = UnityAssetApplicator(manager).apply(
            state["project_id"],
            image_request,
            sound_request,
            image_draft,
            sound_draft,
            image_validation,
            sound_validation,
            include_unvalidated_drafts=game_failed,
            exclude_placeholder_images=exclude_placeholder_images,
            skip_image_application=skip_image_application,
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
            (
                "diagnostic_integrated_unity_project.zip"
                if game_failed
                else "integrated_unity_project.zip"
            ),
            UnityProjectGenerator().create_archive(unity_project_root),
            producer="apply_assets_to_game",
            media_type="application/zip",
        )
        notes = []
        if game_failed:
            notes.append(
                "게임 생성은 실패했지만 진단용 Unity 프로젝트에 검증을 통과한 "
                "이미지/사운드 에셋을 적용함"
            )
        else:
            notes.append("검증을 통과한 에셋을 Unity 프로젝트에 복사하고 바인딩 manifest를 생성함")
        notes.append("Unity Editor가 프로젝트를 열 때 importer 설정과 씬 바인딩을 적용함")
        notes.extend(application.manifest["warnings"])
        integrated_game = {
            "contract_version": CONTRACT_VERSION,
            "status": "failed" if game_failed else "integrated",
            "entry_artifact": archive_reference,
            "game_artifacts": [manifest_reference, archive_reference],
            "asset_binding_manifest": manifest_reference,
            "applied_image_asset_ids": application.applied_image_asset_ids,
            "applied_sound_asset_ids": application.applied_sound_asset_ids,
            "suppressed_placeholder_image_asset_ids": (
                application.suppressed_placeholder_image_asset_ids
            ),
            "notes": notes,
        }
    except Exception as error:
        if not game_failed:
            raise
        integrated_game = {
            "contract_version": CONTRACT_VERSION,
            "status": "failed",
            "entry_artifact": None,
            "game_artifacts": [],
            "applied_image_asset_ids": [],
            "applied_sound_asset_ids": [],
            "suppressed_placeholder_image_asset_ids": [],
            "notes": [
                (
                    "게임 생성 실패 후 진단용 Unity 프로젝트에도 에셋을 적용하지 못함: "
                    f"{type(error).__name__}: {error}"
                )
            ],
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

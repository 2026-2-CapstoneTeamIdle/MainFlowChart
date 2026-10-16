"""Generate image assets for the requested game."""

from __future__ import annotations

import io
from typing import cast

from PIL import Image

from mainflow.ArtifactManager import ArtifactManager
from mainflow.contracts import (
    CONTRACT_VERSION,
    AnalysisResult,
    AssetGenerationRequest,
    GenerateImageAgentInput,
    GenerateImageAgentOutput,
    ImageAsset,
    ImageDraft,
    LogicAnalysis,
    ParsedRequest,
)
from mainflow.image_backends import create_image_generator
from mainflow.image_generation import (
    PNG_MEDIA_TYPE,
    SPRITE_SHEET_NOTE_PREFIX,
    ImageGenerator,
    ImageRequest,
    ReferenceImage,
    build_prompt,
    plan_assets,
)
from mainflow.image_spritesheet import (
    SHEET_MEDIA_TYPE,
    AnimationSpec,
    StripSource,
    animations_for,
    build_sprite_sheet,
    metadata_filename,
    sheet_filename,
    sheet_mode,
    sprite_sheets_enabled,
)
from mainflow.nodes._common import log


# Node 계약
# - 이전 Node: design_game_logic
# - 입력 State: project_id, parsed_request, analysis, logic_analysis, image_asset_request
# - 입력 파일: data/*.json, game/asset_requests/image_asset_request.json,
#   generated/images/references/custom_style.*(Custom 스타일일 때)
# - 출력 State: image_draft(ArtifactReference)
# - 출력 파일: generated/images/{suggested_filename}, generated/images/image_draft.json,
#   캐릭터 스프라이트의 애니메이션 시트 generated/images/{asset}_sheet.png/.json
# - 다음 Node: validate_image (asset_validation_spec과 합류)
def generate_image_node(
    state: GenerateImageAgentInput,
    generator: ImageGenerator | None = None,
) -> GenerateImageAgentOutput:
    """Generate image artifacts and return their immutable draft reference."""
    log("이미지 에셋을 생성합니다.")

    manager = ArtifactManager()
    cast(ParsedRequest, manager.read_json(state["parsed_request"]))
    cast(AnalysisResult, manager.read_json(state["analysis"]))
    cast(LogicAnalysis, manager.read_json(state["logic_analysis"]))
    asset_request = cast(
        AssetGenerationRequest,
        manager.read_json(state["image_asset_request"]),
    )

    reference = None
    if asset_request["reference_image"] is not None:
        reference = ReferenceImage(
            content=manager.read_bytes(asset_request["reference_image"]),
            media_type=asset_request["reference_image"]["media_type"],
        )

    # MAINFLOW_IMAGE_BACKEND로 생성기 선택 (기본값 placeholder)
    generator = generator or create_image_generator()
    assets: list[ImageAsset] = []
    notes = [f"generator={generator.name}"]
    missing_required_asset_ids: list[str] = []
    for plan in plan_assets(asset_request):
        width, height = plan.size
        image_request = ImageRequest(
            plan=plan,
            style=asset_request["image_style"],
            mood_style=asset_request["mood_style"],
            viewpoint=asset_request["viewpoint"],
            genre=asset_request["genre"],
            width=width,
            height=height,
            prompt=build_prompt(plan, asset_request),
            reference=reference,
        )
        try:
            content = generator.generate(image_request)
        except Exception as error:  # 개별 에셋 실패는 draft notes로 기록
            notes.append(f"{plan.asset_id} 생성 실패: {error}")
            if plan.required:
                missing_required_asset_ids.append(plan.asset_id)
            continue
        artifact = manager.write_bytes(
            state["project_id"],
            "image",
            plan.filename,
            content,
            producer="generate_image",
            media_type=PNG_MEDIA_TYPE,
        )
        assets.append(
            {
                "asset_id": plan.asset_id,
                "name": plan.purpose,
                "kind": plan.kind,
                "unity_binding_key": plan.unity_binding_key,
                "artifact": artifact,
                "file_format": "png",
                "width": width,
                "height": height,
                "prompt": image_request.prompt,
            }
        )
        log(f"  - {plan.asset_id} ({plan.kind}, {width}x{height}) 저장")

        # MAINFLOW_IMAGE_SPRITE_SHEETS=off로 끌 수 있다 (기본값 on)
        animations = animations_for(plan, asset_request["genre"])
        if not animations or not sprite_sheets_enabled():
            continue
        strip_source = _strip_source(generator, image_request, content, sheet_mode())
        if strip_source is None and sheet_mode() == "ai":
            notes.append(
                f"{plan.asset_id}: {generator.name} 백엔드는 AI 스프라이트 시트를 지원하지 않아 "
                "transform으로 생성"
            )
        try:
            sheet, metadata = build_sprite_sheet(
                content, plan, animations, asset_request["image_style"], strip_source
            )
        except Exception as error:  # 시트는 부가 산출물이므로 실패해도 기본 에셋은 유지
            notes.append(f"{plan.asset_id} 스프라이트 시트 생성 실패: {error}")
            continue
        for name, reason in metadata.get("fallbacks", {}).items():
            message = f"{plan.asset_id} {name} AI 프레임 실패, transform으로 대체: {reason}"
            notes.append(message)
            log(f"  ! {message}")
        sheet_artifact = manager.write_bytes(
            state["project_id"],
            "image",
            sheet_filename(plan),
            sheet,
            producer="generate_image",
            media_type=SHEET_MEDIA_TYPE,
        )
        metadata["sheet_relative_path"] = sheet_artifact["relative_path"]
        metadata_artifact = manager.write_json(
            state["project_id"],
            "image",
            metadata_filename(plan),
            metadata,
            producer="generate_image",
        )
        notes.append(
            f"{SPRITE_SHEET_NOTE_PREFIX}{plan.asset_id}="
            f"{sheet_artifact['artifact_id']},{metadata_artifact['artifact_id']}"
        )
        summary = ", ".join(
            f"{name}:{animation['source']}" for name, animation in metadata["animations"].items()
        )
        log(f"  - {plan.asset_id} 스프라이트 시트 ({summary}) 저장")

    if getattr(generator, "transparent_supported", True) is False:
        notes.append(
            "투명 배경을 지원하지 않는 모델이라 흰 단색 배경으로 생성한 뒤 후처리로 배경을 제거함"
        )

    draft: ImageDraft = {
        "contract_version": CONTRACT_VERSION,
        "draft_id": "image-draft",
        "status": "failed" if missing_required_asset_ids else "generated",
        "assets": assets,
        "missing_required_asset_ids": missing_required_asset_ids,
        "notes": notes,
    }
    return {
        "image_draft": manager.write_json(
            state["project_id"],
            "image",
            "image_draft.json",
            draft,
            producer="generate_image",
        )
    }


def _strip_source(
    generator: ImageGenerator,
    image_request: ImageRequest,
    sprite_png: bytes,
    mode: str,
) -> StripSource | None:
    """Return a callable that draws one animation strip, if ai sheets apply."""

    draw_strip = getattr(generator, "generate_animation_strip", None)
    if mode == "transform" or draw_strip is None:
        return None
    raw_outputs: dict[str, bytes] = getattr(generator, "raw_outputs", {})
    reference = raw_outputs.get(image_request.plan.asset_id) or _upscale(sprite_png)

    def source(animation: AnimationSpec) -> bytes:
        return draw_strip(
            image_request,
            reference,
            animation.name,
            len(animation.keyframes),
            animation.ai_description,
        )

    return source


def _upscale(png: bytes, factor: int = 8) -> bytes:
    """Pixel-exact enlargement so a small sprite works as a reference image."""

    with Image.open(io.BytesIO(png)) as source:
        image = source.convert("RGBA")
    enlarged = image.resize((image.width * factor, image.height * factor), Image.Resampling.NEAREST)
    output = io.BytesIO()
    enlarged.save(output, format="PNG")
    return output.getvalue()

"""Generate image assets for the requested game."""

from __future__ import annotations

from typing import cast

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
    ImageGenerator,
    ImageRequest,
    ReferenceImage,
    build_prompt,
    plan_assets,
)
from mainflow.nodes._common import log


# Node 계약
# - 이전 Node: design_game_logic
# - 입력 State: project_id, parsed_request, analysis, logic_analysis, image_asset_request
# - 입력 파일: data/*.json, game/asset_requests/image_asset_request.json,
#   generated/images/references/custom_style.*(Custom 스타일일 때)
# - 출력 State: image_draft(ArtifactReference)
# - 출력 파일: generated/images/{suggested_filename}, generated/images/image_draft.json
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

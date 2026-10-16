"""Shared contract-3.3.0 payloads for the image node tests."""

from __future__ import annotations

from typing import Any

from game_pipeline.asset_specs import build_image_generation_spec
from mainflow.ArtifactManager import ArtifactManager
from mainflow.contracts import (
    CONTRACT_VERSION,
    ArtifactReference,
    AssetGenerationItem,
    AssetGenerationRequest,
)
from mainflow.image_generation import image_criteria


def asset_item(
    asset_id: str,
    purpose: str,
    description: str,
    *,
    required: bool = True,
) -> AssetGenerationItem:
    return {
        "asset_id": asset_id,
        "asset_type": "image",
        "purpose": purpose,
        "description": description,
        "required": required,
        "suggested_filename": f"{asset_id}.png",
        "unity_binding_key": f"asset_registry:{asset_id}",
        "generation_spec": build_image_generation_spec(purpose, description),
    }


PLATFORMER_ASSETS = [
    asset_item("platformer_player", "플레이어", "좌우 이동과 점프 캐릭터 스프라이트"),
    asset_item("platformer_tileset", "맵", "발판과 지형 타일셋"),
]


def image_asset_request(
    assets: list[AssetGenerationItem] | None = None,
    *,
    image_style: str = "Pixel Art",
    reference_image: ArtifactReference | None = None,
) -> AssetGenerationRequest:
    return {
        "contract_version": CONTRACT_VERSION,
        "request_id": "design-image-assets",
        "source_design_id": "design",
        "game_title": "Sky Runner",
        "genre": "Platformer",
        "asset_type": "image",
        "image_style": image_style,  # type: ignore[typeddict-item]
        "mood_style": "Fantasy",
        "viewpoint": "사이드뷰",
        "reference_image": reference_image,
        "output_directory": "generated/images",
        "assets": PLATFORMER_ASSETS if assets is None else assets,
    }


def write_image_inputs(
    manager: ArtifactManager,
    project_id: str,
    request: AssetGenerationRequest,
) -> dict[str, Any]:
    """Write the upstream artifacts and return generate/validate node state."""

    def write(category: Any, filename: str, payload: Any) -> ArtifactReference:
        return manager.write_json(project_id, category, filename, payload, producer="test")

    return {
        "project_id": project_id,
        "parsed_request": write(
            "data",
            "parsed_request.json",
            {
                "contract_version": CONTRACT_VERSION,
                "image_style": request["image_style"],
                "mood_style": request["mood_style"],
                "genre": "플랫포머",
                "viewpoint": request["viewpoint"],
                "condition": "점프가 가능한 게임",
                "custom_image": request["reference_image"],
            },
        ),
        "analysis": write(
            "data",
            "analysis.json",
            {
                "contract_version": CONTRACT_VERSION,
                "analysis_id": "analysis",
                "condition_summary": "점프가 가능한 게임",
                "features": [],
            },
        ),
        "logic_analysis": write(
            "data",
            "logic_analysis.json",
            {
                "contract_version": CONTRACT_VERSION,
                "logic_analysis_id": "logic",
                "genre": "플랫포머",
                "viewpoint": request["viewpoint"],
                "mood_style": request["mood_style"],
                "core_loop": "jump",
                "features": [],
                "criteria": [],
            },
        ),
        "image_asset_request": write("game", "asset_requests/image_asset_request.json", request),
        "asset_validation_spec": write(
            "validation",
            "asset_validation_spec.json",
            {
                "contract_version": CONTRACT_VERSION,
                "spec_id": "asset-validation",
                "image_criteria": image_criteria(),
                "sound_criteria": [],
            },
        ),
    }

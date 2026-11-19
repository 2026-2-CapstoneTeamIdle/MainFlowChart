"""Turn CLI agents' request-specific scene objects into image generation requests."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any, cast

from game_pipeline.asset_specs import build_image_generation_spec
from mainflow.contracts import AssetGenerationItem, AssetGenerationRequest, ImageAssetKind

_ASSET_ID = re.compile(r"[a-z][a-z0-9_]{2,63}")
_OBJECT_PREFIX = re.compile(r"[A-Za-z][A-Za-z0-9_]{2,63}")
_IMAGE_KINDS: frozenset[str] = frozenset(
    {"sprite", "ui", "background", "tileset", "illustration", "portrait"}
)
MAX_ADDITIONAL_VISUALS = 64


def with_agent_visual_assets(
    request: AssetGenerationRequest,
    reports: Sequence[Mapping[str, Any]],
) -> tuple[AssetGenerationRequest, list[str]]:
    """Add distinct object art that the agent explicitly connected to scene or runtime code.

    The agent names objects after implementing the request, so this list can cover novel
    condition-specific content that a genre preset cannot enumerate in advance.
    """
    if request["asset_type"] != "image":
        raise ValueError("Agent visual objects can only extend an image request")

    assets = list(request["assets"])
    existing_ids = {item["asset_id"] for item in assets}
    added: list[str] = []
    for report in reports:
        proposed = report.get("visual_objects", [])
        if not isinstance(proposed, list):
            continue
        for object_spec in proposed:
            if len(added) >= MAX_ADDITIONAL_VISUALS:
                break
            if not isinstance(object_spec, Mapping):
                continue
            raw_id = object_spec.get("asset_id")
            prefix = object_spec.get("scene_object_prefix")
            purpose = object_spec.get("purpose")
            description = object_spec.get("description")
            kind = object_spec.get("kind")
            if not all(isinstance(value, str) for value in (raw_id, prefix, purpose, description)):
                continue
            asset_id = cast(str, raw_id).strip().lower()
            prefix = cast(str, prefix).strip()
            purpose = cast(str, purpose).strip()
            description = cast(str, description).strip()
            if (
                not _ASSET_ID.fullmatch(asset_id)
                or asset_id in existing_ids
                or not _OBJECT_PREFIX.fullmatch(prefix)
                or not purpose
                or not description
                or kind not in _IMAGE_KINDS
            ):
                continue

            if kind == "background":
                description += (
                    " Seamlessly repeatable scenery in both horizontal and vertical directions; "
                    "preserve fine pixel-art detail at normal camera zoom, with no characters "
                    "or large flat-color blocks."
                )

            item = cast(
                AssetGenerationItem,
                {
                    "asset_id": asset_id,
                    "asset_type": "image",
                    "purpose": purpose[:120],
                    "description": description[:800],
                    "required": False,
                    "suggested_filename": f"{asset_id}.png",
                    "unity_binding_key": (
                        f"ui_object_prefix:{prefix}"
                        if kind == "ui"
                        else f"scene_object_prefix:{prefix}"
                    ),
                    "generation_spec": build_image_generation_spec(
                        purpose,
                        description,
                        asset_id,
                        kind_override=cast(ImageAssetKind, kind),
                    ),
                },
            )
            assets.append(item)
            existing_ids.add(asset_id)
            added.append(asset_id)
    return cast(AssetGenerationRequest, {**request, "assets": assets}), added

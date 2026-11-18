"""Request UI artwork for the HUD described by the presentation contract."""

from __future__ import annotations

from typing import Any, cast

from game_pipeline.asset_specs import build_image_generation_spec
from mainflow.contracts import AssetGenerationItem, AssetGenerationRequest


HUD_ART: tuple[tuple[str, str, str, str], ...] = (
    (
        "hud_panel_frame",
        "HudArt_",
        "Reusable HUD panel decoration",
        "A restrained dark game UI panel frame with a dark translucent center and subtle border; "
        "no words, letters, digits, symbols, or controls. Keep the central text area quiet.",
    ),
    (
        "hud_icon_health",
        "HudIconHealth",
        "Health HUD icon",
        "A small readable health emblem for a live health counter; no text or digits.",
    ),
    (
        "hud_icon_currency",
        "HudIconCurrency",
        "Currency HUD icon",
        "A small readable currency emblem for a live gold or resource counter; no text or digits.",
    ),
    (
        "hud_icon_wave",
        "HudIconWave",
        "Wave HUD icon",
        "A small readable enemy-wave emblem for a live wave counter; no text or digits.",
    ),
    (
        "hud_icon_timer",
        "HudIconTimer",
        "Timer HUD icon",
        "A small readable time emblem for a live timer; no text or digits.",
    ),
    (
        "hud_icon_objective",
        "HudIconObjective",
        "Objective HUD icon",
        "A small readable objective or collection emblem for live progress; no text or digits.",
    ),
)

_ICON_TERMS: dict[str, tuple[str, ...]] = {
    "hud_icon_health": ("health", "hp", "lives", "체력", "생명", "기지"),
    "hud_icon_currency": ("gold", "currency", "resource", "score", "골드", "자원", "점수"),
    "hud_icon_wave": ("wave", "enemy", "웨이브", "적"),
    "hud_icon_timer": ("time", "timer", "시간", "타이머"),
    "hud_icon_objective": ("objective", "collect", "fragment", "goal", "목표", "수집", "파편"),
}


def with_presentation_ui_assets(
    request: AssetGenerationRequest, ui_contract: dict[str, Any]
) -> tuple[AssetGenerationRequest, list[str]]:
    """Add panel art and only the icons suggested by actual HUD data fields."""
    if request["asset_type"] != "image":
        raise ValueError("HUD art requires an image asset request")
    regions = ui_contract.get("hud_regions", [])
    if not isinstance(regions, list) or not regions:
        return request, []
    visible_data = " ".join(
        str(value).lower()
        for region in regions
        if isinstance(region, dict)
        for value in region.get("visible_data", [])
    )
    assets = list(request["assets"])
    existing = {item["asset_id"] for item in assets}
    added: list[str] = []
    for asset_id, prefix, purpose, description in HUD_ART:
        if asset_id in existing or (
            asset_id != "hud_panel_frame"
            and not any(term in visible_data for term in _ICON_TERMS[asset_id])
        ):
            continue
        assets.append(
            cast(
                AssetGenerationItem,
                {
                    "asset_id": asset_id,
                    "asset_type": "image",
                    "purpose": purpose,
                    "description": description,
                    "required": False,
                    "suggested_filename": f"{asset_id}.png",
                    "unity_binding_key": f"ui_object_prefix:{prefix}",
                    "generation_spec": build_image_generation_spec(
                        purpose, description, asset_id, kind_override="ui"
                    ),
                },
            )
        )
        added.append(asset_id)
    return cast(AssetGenerationRequest, {**request, "assets": assets}), added

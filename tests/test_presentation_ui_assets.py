from __future__ import annotations

from typing import cast

from game_pipeline.presentation_ui_assets import with_presentation_ui_assets
from mainflow.contracts import AssetGenerationRequest


def test_hud_art_requests_only_icons_for_visible_data() -> None:
    request = cast(AssetGenerationRequest, {"asset_type": "image", "assets": []})
    updated, added = with_presentation_ui_assets(
        request,
        {
            "hud_regions": [
                {"region_id": "status", "visible_data": ["gold", "base health", "wave"]},
                {"region_id": "notice", "visible_data": ["status banner"]},
            ]
        },
    )

    assert added == [
        "hud_panel_frame",
        "hud_icon_health",
        "hud_icon_currency",
        "hud_icon_wave",
    ]
    assert all(item["required"] is False for item in updated["assets"])
    assert all(item["generation_spec"]["kind"] == "ui" for item in updated["assets"])
    assert updated["assets"][0]["unity_binding_key"] == "ui_object_prefix:HudArt_"
    assert "nine-slice" in updated["assets"][0]["description"]
    assert "84 percent" in updated["assets"][0]["description"]
    assert updated["assets"][0]["generation_spec"]["transparent"] is True
    assert all(item["generation_spec"]["transparent"] is True for item in updated["assets"][1:])
    assert (
        with_presentation_ui_assets(updated, {"hud_regions": [{"visible_data": ["gold"]}]})[1] == []
    )

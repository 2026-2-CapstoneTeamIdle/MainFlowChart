"""Derive sound requests from presentation feedback instead of genre presets alone."""

from __future__ import annotations

import re
from typing import cast

from mainflow.contracts import AssetRequirement, GameSpec, PresentationPlan


def feedback_sound_asset_id(cue_id: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", cue_id.strip().lower()).strip("_")
    return f"{normalized or 'feedback'}_sfx"


def with_presentation_sound_assets(
    game_spec: GameSpec, presentation_plan: PresentationPlan
) -> GameSpec:
    """Add one bindable sound requirement for every authored feedback cue."""

    existing_ids = {item["asset_id"] for item in game_spec["asset_requirements"]}
    additions: list[AssetRequirement] = []
    for cue in presentation_plan.get("feedback_cues", []):
        cue_id = str(cue.get("cue_id", "")).strip()
        if not cue_id:
            continue
        asset_id = feedback_sound_asset_id(cue_id)
        if asset_id in existing_ids:
            continue
        additions.append(
            {
                "asset_id": asset_id,
                "asset_type": "sound",
                "purpose": f"{cue_id} feedback",
                "description": (
                    f"One-shot gameplay feedback for {cue.get('trigger', cue_id)}. "
                    "Keep it distinct and immediately recognizable in a busy game mix."
                ),
                "required": True,
            }
        )
        existing_ids.add(asset_id)
    if not additions:
        return game_spec
    return cast(
        GameSpec,
        {
            **game_spec,
            "asset_requirements": [*game_spec["asset_requirements"], *additions],
        },
    )

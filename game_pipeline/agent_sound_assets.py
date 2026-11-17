"""Add request-specific, implemented gameplay sounds to the asset request."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any, cast

from game_pipeline.asset_specs import build_sound_generation_spec
from mainflow.contracts import AssetGenerationItem, AssetGenerationRequest, SoundAssetKind

_IDENTIFIER = re.compile(r"[a-z][a-z0-9_]{2,63}")
_SOUND_KINDS: frozenset[str] = frozenset({"bgm", "sfx", "ui", "voice", "ambience"})
MAX_ADDITIONAL_SOUNDS = 64


def with_agent_sound_assets(
    request: AssetGenerationRequest,
    reports: Sequence[Mapping[str, Any]],
) -> tuple[AssetGenerationRequest, list[str]]:
    """Request distinct sounds whose exact gameplay cue was authored by the agent."""
    if request["asset_type"] != "sound":
        raise ValueError("Agent sound events can only extend a sound request")

    assets = list(request["assets"])
    existing_ids = {item["asset_id"] for item in assets}
    existing_cues = {
        str(item["generation_spec"].get("audio_cue", ""))
        for item in assets
        if item["generation_spec"].get("audio_cue")
    }
    added: list[str] = []
    for report in reports:
        proposed = report.get("sound_events", [])
        if not isinstance(proposed, list):
            continue
        for event in proposed:
            if len(added) >= MAX_ADDITIONAL_SOUNDS:
                break
            if not isinstance(event, Mapping):
                continue
            raw_id = event.get("asset_id")
            raw_cue = event.get("cue_id")
            purpose = event.get("purpose")
            description = event.get("description")
            kind = event.get("kind")
            if not all(isinstance(value, str) for value in (raw_id, raw_cue, purpose, description)):
                continue
            asset_id = cast(str, raw_id).strip().lower()
            cue_id = cast(str, raw_cue).strip().lower()
            purpose = cast(str, purpose).strip()
            description = cast(str, description).strip()
            if (
                not _IDENTIFIER.fullmatch(asset_id)
                or asset_id in existing_ids
                or not _IDENTIFIER.fullmatch(cue_id)
                or cue_id in existing_cues
                or not purpose
                or not description
                or kind not in _SOUND_KINDS
            ):
                continue

            assets.append(
                cast(
                    AssetGenerationItem,
                    {
                        "asset_id": asset_id,
                        "asset_type": "sound",
                        "purpose": purpose[:120],
                        "description": description[:800],
                        "required": False,
                        "suggested_filename": f"{asset_id}.wav",
                        "unity_binding_key": f"asset_registry:{asset_id}",
                        "generation_spec": build_sound_generation_spec(
                            purpose,
                            description,
                            kind_override=cast(SoundAssetKind, kind),
                            cue_override=cue_id,
                        ),
                    },
                )
            )
            existing_ids.add(asset_id)
            existing_cues.add(cue_id)
            added.append(asset_id)
    return cast(AssetGenerationRequest, {**request, "assets": assets}), added

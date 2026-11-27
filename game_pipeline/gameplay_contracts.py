"""Request-specific pacing and player-facing UI acceptance contracts."""

from __future__ import annotations

import re
from typing import Any

from mainflow.contracts import DesignV2Bundle, GameSpec


_DURATION_PATTERNS = (
    re.compile(r"(?:약\s*)?(\d{1,2})\s*분(?:\s*(?:분량|동안|플레이))?"),
    re.compile(r"\b(\d{1,2})\s*[- ]?minute(?:s)?\b", re.IGNORECASE),
)
_ZONE_PATTERNS = (
    re.compile(r"(?:최소\s*)?(\d{1,2})\s*개(?:의)?\s*구역"),
    re.compile(r"\b(?:at least\s+)?(\d{1,2})\s+zones?\b", re.IGNORECASE),
)
_KOREAN_ZONE_COUNT = {"세": 3, "네": 4, "다섯": 5, "여섯": 6}
_KOREAN_ZONE_PATTERNS = (
    re.compile(r"(?:최소\s*)?(세|네|다섯|여섯)\s*개(?:의)?\s*구역"),
    re.compile(r"구역\s*(세|네|다섯|여섯)\s*개"),
)
_COLLECTIBLE_PATTERNS = (
    re.compile(r"(?:파편|보석|수집물|shards?|collectibles?).{0,18}?(\d{1,3})\s*개", re.I),
    re.compile(r"(\d{1,3})\s*개.{0,12}?(?:파편|보석|수집물|shards?|collectibles?)", re.I),
)


def compact_platformer_requested(condition: str) -> bool:
    """Recognize an explicitly short single-stage prototype without a duration target."""

    if any(pattern.search(condition) for pattern in _DURATION_PATTERNS):
        return False
    normalized = condition.lower()
    short = any(word in normalized for word in ("짧은", "간단한", "소규모", "short", "compact"))
    single_stage = bool(
        re.search(
            r"(?:하나의|단일|한\s*개(?:의)?|1\s*개(?:의)?|one|single)"
            r".{0,12}(?:스테이지|레벨|stage|level)"
            r"|(?:스테이지|레벨|stage|level).{0,8}"
            r"(?:하나|한\s*개|1\s*개|one|single)",
            normalized,
        )
    )
    few_platforms = (count := requested_platform_count(condition)) is not None and count <= 10
    return single_stage and (short or few_platforms)


def trim_compact_platformer_spec(game_spec: GameSpec, condition: str) -> GameSpec:
    """Remove preset systems contradicted by a small single-stage request."""

    if game_spec["genre"] != "Platformer" or not compact_platformer_requested(condition):
        return game_spec
    excluded = {"health_damage", "collectible", "item_collect", "player_stats", "score"}
    if requested_collectible_count(condition) is not None:
        excluded -= {"collectible", "item_collect"}
    return {
        **game_spec,
        "mechanics": [item for item in game_spec["mechanics"] if item not in excluded],
        "lose_conditions": [],
    }


def requested_play_minutes(condition: str, *, default: int = 5) -> int:
    """Use zero for an explicitly compact run with no requested duration."""

    for pattern in _DURATION_PATTERNS:
        match = pattern.search(condition)
        if match:
            return max(1, min(30, int(match.group(1))))
    return 0 if compact_platformer_requested(condition) else default


def requested_platform_count(condition: str) -> int | None:
    """Preserve an explicit fixed-platform count in a compact stage."""

    for pattern in (
        re.compile(r"(\d{1,2})\s*개(?:의)?\s*(?:고정\s*)?발판"),
        re.compile(r"(?:고정\s*)?발판\s*(\d{1,2})\s*개"),
        re.compile(r"(\d{1,2})\s+(?:fixed\s+)?platforms?\b", re.I),
    ):
        match = pattern.search(condition)
        if match:
            return max(2, min(60, int(match.group(1))))
    return None


def requested_zone_count(condition: str, *, default: int) -> int:
    """Preserve an explicitly requested number of platformer areas."""

    for pattern in _ZONE_PATTERNS:
        match = pattern.search(condition)
        if match:
            return max(3, min(12, int(match.group(1))))
    for pattern in _KOREAN_ZONE_PATTERNS:
        korean_match = pattern.search(condition)
        if korean_match:
            return _KOREAN_ZONE_COUNT[korean_match.group(1)]
    return default


def requested_collectible_count(condition: str) -> int | None:
    """Find an explicit authored collectible quantity without treating enemy counts as rewards."""

    for pattern in _COLLECTIBLE_PATTERNS:
        match = pattern.search(condition)
        if match:
            return max(1, min(100, int(match.group(1))))
    return None


def checkpoint_respawn_requested(condition: str) -> bool:
    """Health-zero checkpoint recovery is a retry transition, not a defeat screen."""

    normalized = condition.lower()
    return (
        ("체력" in normalized or "health" in normalized)
        and ("체크포인트" in normalized or "checkpoint" in normalized)
        and any(token in normalized for token in ("부활", "복귀", "respawn", "return"))
    )


def build_pacing_contract(
    game_spec: GameSpec, design: DesignV2Bundle, condition: str
) -> dict[str, Any]:
    """Record the intended human playtime separately from accelerated tests."""

    target_minutes = requested_play_minutes(condition)
    design_minutes = int(design["game_design"]["target_play_minutes"])
    if design_minutes != target_minutes:
        raise ValueError(
            f"game_design target_play_minutes={design_minutes} conflicts with "
            f"requested playtime {target_minutes}"
        )
    genre = game_spec["genre"]
    level = design["level_plan"]
    progression_units = {
        "Platformer": len(level["zones"]),
        "TowerDefense": max(1, len(level["zones"])),
        "SurvivorLike": max(1, len(level["zones"])),
    }.get(genre, max(1, len(level["zones"])))
    segments = [
        {
            "segment_id": f"segment_{index + 1}",
            "source_zone_id": (
                level["zones"][index]["zone_id"] if index < len(level["zones"]) else None
            ),
            "content_goal": (
                "Distinct traversal and mechanic challenge with a reachable reward or checkpoint"
                if genre == "Platformer"
                else "Distinct encounter or meaningful player decision with visible progress"
            ),
        }
        for index in range(progression_units)
    ]
    compact = genre == "Platformer" and compact_platformer_requested(condition)
    acceptance = [
        "Measure an unaccelerated start-to-result run with real player controls when available; lack of that measurement alone is an evidence limitation.",
        "Never lock a zone boundary or the goal until a minimum timer elapses just to satisfy playtime.",
        "Every segment must contain authored traversal, combat, decisions, or challenge content; repeated movement against a gate does not count.",
        "The final objective and all required collectibles must be reachable from player spawn with the implemented movement abilities.",
    ]
    if compact:
        acceptance.append("This short single-stage prototype has no minimum playtime requirement.")
    else:
        acceptance.insert(
            1,
            "Normal play should last at least minimum_normal_play_seconds through authored content; a fast automated smoke test is not duration evidence.",
        )
    return {
        "contract_version": "1.0.0",
        "genre": genre,
        "target_play_minutes": target_minutes,
        "target_duration_seconds": target_minutes * 60,
        "minimum_normal_play_seconds": (
            0 if compact else max(60, round(target_minutes * 60 * 0.75))
        ),
        "segments": segments,
        "acceptance": acceptance,
    }


def build_ui_contract(game_spec: GameSpec, design: DesignV2Bundle) -> dict[str, Any]:
    """Turn presentation requirements into runtime data and screen checks."""

    presentation = design["presentation_plan"]
    return {
        "contract_version": "1.0.0",
        "genre": game_spec["genre"],
        "reference_resolution": [1280, 720],
        "second_resolution": [1920, 1080],
        "hud_regions": [
            {
                "region_id": region["region_id"],
                "anchor": region["anchor"],
                "visible_data": list(region["visible_data"]),
                "binding_rule": "Read live gameplay state and refresh when the value changes; no sample constants.",
            }
            for region in presentation["hud_layout"]
        ],
        "state_screens": [
            {
                "screen_id": screen["screen_id"],
                "activation_condition": screen["activation_condition"],
                "required_elements": list(screen["required_elements"]),
            }
            for screen in presentation["screen_requirements"]
        ],
        "acceptance": [
            "Use anchored uGUI and CanvasScaler.ScaleWithScreenSize; keep controls readable at both reference resolutions.",
            "Every visible counter, bar, timer, and objective is bound to the corresponding runtime state and updates after a state transition.",
            "Every required screen appears at its activation condition and exposes functional primary actions.",
            "The HUD must not obstruct world interaction points or hide required progression objects.",
            "Every HUD value and announcement has a readable backing panel with high-contrast live text, not text painted into a generated image.",
            "Generated HUD frames and icons are decorative uGUI Images behind live text; missing artwork keeps the readable panel fallback.",
            "After asset import, capture the UI and inspect text contrast and screen clipping at the reference resolution.",
        ],
    }

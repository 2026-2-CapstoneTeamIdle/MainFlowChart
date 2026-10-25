"""Compile a game request into scene-assembly data instead of a fixed sample scene."""

from __future__ import annotations

import hashlib
import random
import re

from mainflow.contracts import (
    BlueprintContentDirective,
    BlueprintEntity,
    BlueprintProgressionOption,
    GameBlueprint,
    GameSpec,
)

_PALETTES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("#151B35", ("판타지", "fantasy", "마법", "날개")),
    ("#28151A", ("공포", "horror", "괴물", "어둠")),
    ("#132A2B", ("바다", "forest", "숲", "자연")),
    ("#2A1A36", ("사이버", "neon", "우주")),
    ("#24201A", ("학교", "일상", "cozy")),
)
_ENTITY_COLORS = ("#5EC8FF", "#FF9E4F", "#A78BFA", "#52D695", "#F5D94F")


def build_game_blueprint(
    game_spec: GameSpec,
    design_intent: str,
    *,
    variation_seed: str = "",
) -> GameBlueprint:
    """Return a deterministic, input-specific scene blueprint.

    It is intentionally data-only: a later LLM planner can replace this
    function's output without changing the Unity generator or assembler.
    """

    intent = design_intent.strip() or "기본 장르 프로토타입"
    seed = int(
        hashlib.sha256(
            (
                f"{game_spec['genre']}|{game_spec['title']}|{intent}|variation:{variation_seed}"
            ).encode()
        ).hexdigest()[:16],
        16,
    )
    rng = random.Random(seed)
    summary = _summary(intent, game_spec)
    content = _content_directives(game_spec, rng)
    entities = _entities(game_spec, intent, rng)
    return {
        "blueprint_version": "1.0.0",
        "blueprint_id": f"{game_spec['genre'].lower()}-{seed:016x}",
        "source": "deterministic",
        "title": game_spec["title"],
        "summary": summary,
        "scene_width": float(rng.choice((24, 28, 32, 36))),
        "scene_height": float(rng.choice((14, 16, 18, 20))),
        "background_color_hex": _background_color(intent),
        "core_loop": _core_loop(game_spec),
        "content": content,
        "entities": entities,
        "progression_options": _progression(game_spec, intent),
        "ui_labels": _ui_labels(game_spec),
    }


def _summary(intent: str, game_spec: GameSpec) -> str:
    features = ", ".join(feature["description"] for feature in game_spec["features"][:3])
    return f"{intent}. {game_spec['genre']} 핵심 기능: {features}"


def _core_loop(game_spec: GameSpec) -> list[str]:
    base = {
        "Platformer": ["탐색", "장애물 돌파", "수집", "목표 도달"],
        "TowerDefense": ["배치", "웨이브 방어", "자원 획득", "강화"],
        "CardGame": ["드로우", "카드 사용", "자원 관리", "승리 판정"],
        "VisualNovel": ["장면 읽기", "선택", "플래그 갱신", "분기"],
        "RaisingSimulation": ["행동 선택", "능력치 변화", "시간 경과", "목표 판정"],
        "SurvivorLike": ["이동", "적 처치", "경험치 획득", "특전 선택"],
    }
    return base[game_spec["genre"]]


def _content_directives(game_spec: GameSpec, rng: random.Random) -> list[BlueprintContentDirective]:
    # Vary fixed preset counts in a safe range; existing modules still own behavior.
    base_counts = {
        "Platformer": (("platform", 10), ("collectible", 8), ("hazard", 5), ("enemy", 3)),
        "TowerDefense": (("wave", 5), ("tower_slot", 6), ("enemy", 12), ("path_marker", 6)),
        "CardGame": (("card", 20), ("starting_hand_slot", 5), ("opponent", 1), ("reward", 3)),
        "VisualNovel": (("dialogue_line", 40), ("choice", 5), ("character", 3), ("scene", 3)),
        "RaisingSimulation": (("activity", 8), ("stat", 4), ("event", 6), ("ending", 3)),
        "SurvivorLike": (("arena_marker", 20), ("enemy", 24), ("upgrade", 8), ("elite", 3)),
    }[game_spec["genre"]]
    return [
        {
            "archetype": archetype,
            "count": max(1, round(count * rng.uniform(0.75, 1.35))),
            "purpose": f"{archetype} 콘텐츠 밀도",
        }
        for archetype, count in base_counts
    ]


def _entities(game_spec: GameSpec, intent: str, rng: random.Random) -> list[BlueprintEntity]:
    entities: list[BlueprintEntity] = [
        _entity("player_anchor", "플레이어 시작 지점", "player_anchor", -6.0, -2.4, "#5EC8FF"),
        _entity("objective", "핵심 목표", "objective", 8.5, -2.2, "#52D695"),
    ]
    for index, feature in enumerate(game_spec["features"]):
        angle = index * 1.7 + rng.random()
        entities.append(
            _entity(
                _safe_id(feature["feature_id"], f"feature_{index + 1}"),
                feature["description"][:28],
                "feature_marker",
                round(rng.uniform(-8.0, 9.0), 2),
                round(rng.uniform(-3.0, 4.0), 2),
                _ENTITY_COLORS[index % len(_ENTITY_COLORS)],
                ["feature", f"angle:{angle:.2f}"],
            )
        )
    landmark_count = 3 + rng.randrange(3)
    for index in range(landmark_count):
        entities.append(
            _entity(
                f"landmark_{index + 1}",
                f"{_theme_word(intent, index)} 랜드마크 {index + 1}",
                "landmark",
                round(rng.uniform(-11.0, 11.0), 2),
                round(rng.uniform(-3.4, 4.5), 2),
                _ENTITY_COLORS[(index + 2) % len(_ENTITY_COLORS)],
                ["decorative"],
            )
        )
    return entities


def _entity(
    entity_id: str,
    display_name: str,
    archetype: str,
    position_x: float,
    position_y: float,
    color_hex: str,
    behavior_tags: list[str] | None = None,
) -> BlueprintEntity:
    return {
        "entity_id": entity_id,
        "display_name": display_name,
        "archetype": archetype,
        "position_x": position_x,
        "position_y": position_y,
        "scale_x": 0.55 if archetype == "feature_marker" else 0.8,
        "scale_y": 0.55 if archetype == "feature_marker" else 0.8,
        "color_hex": color_hex,
        "behavior_tags": behavior_tags or [],
    }


def _progression(game_spec: GameSpec, intent: str) -> list[BlueprintProgressionOption]:
    if game_spec["genre"] != "SurvivorLike":
        return []
    names = ("공격력 강화", "이동 속도 강화", "무기 확장", "최대 체력 강화")
    rarities = ("common", "rare", "epic", "legendary")
    return [
        {
            "option_id": f"upgrade_{index + 1}",
            "display_name": name,
            "description": f"{intent[:24]}에 맞춘 {name}",
            "rarity": rarities[index],  # type: ignore[typeddict-item]
        }
        for index, name in enumerate(names)
    ]


def _ui_labels(game_spec: GameSpec) -> list[str]:
    return ["HUD", "Pause", *game_spec["controls"].keys(), "Progression"]


def _background_color(intent: str) -> str:
    normalized = intent.lower()
    for color, keywords in _PALETTES:
        if any(keyword in normalized for keyword in keywords):
            return color
    return "#1B2336"


def _theme_word(intent: str, index: int) -> str:
    words = re.findall(r"[가-힣A-Za-z0-9]+", intent)
    return words[index % len(words)] if words else "프로토타입"


def _safe_id(value: str, fallback: str) -> str:
    normalized = re.sub(r"[^a-z0-9_]+", "_", value.lower()).strip("_")
    return normalized if normalized and normalized[0].isalpha() else fallback

"""Map analyzed user features to reusable or dynamically generated mechanics."""

from __future__ import annotations

import re
from dataclasses import dataclass

from mainflow.contracts import FeatureRequirement, GameFeature, GameGenre

FEATURE_MODULE_MECHANICS: dict[str, tuple[str, ...]] = {
    "좌우 이동": ("platformer_movement",),
    "8방향 이동": ("top_down_movement",),
    "자동 공격": ("auto_target", "projectile"),
    "공격": ("projectile",),
    "점프": ("platformer_movement",),
    "벽 타기": ("wall_climb",),
    "공중 대시": ("air_dash",),
    "카드 덱 구성": ("deck",),
    "대화 선택": ("choice", "branching"),
    "체력 및 피해": ("health_damage",),
    "옵션": ("options",),
    "아이템 수집": ("item_collect",),
    "타워 업그레이드": ("tower_upgrade",),
    "플레이어 스탯": ("player_stats",),
    "점수 기록": ("score",),
    "게임 타이머": ("game_timer",),
    "저장 및 불러오기": ("save_load",),
}

DYNAMIC_FEATURE_BLUEPRINTS: dict[str, dict[str, str]] = {}


@dataclass(frozen=True)
class FeatureMechanicPlan:
    game_features: list[GameFeature]
    mechanics: list[str]
    generation_requirements: dict[str, dict[str, str]]


def plan_feature_mechanics(
    features: list[FeatureRequirement],
    genre: GameGenre,
) -> FeatureMechanicPlan:
    """Reuse known mechanics and mark only unsupported behavior for Gemini."""

    game_features: list[GameFeature] = []
    mechanics: list[str] = []
    requirements: dict[str, dict[str, str]] = {}

    for index, feature in enumerate(features, start=1):
        feature_id = _safe_identifier(feature["feature_id"], f"feature_{index:02d}")
        game_features.append(
            {
                "feature_id": feature_id,
                "description": feature["description"],
                "required": True,
            }
        )
        mapped = _mapped_mechanics(feature["name"], genre, feature["description"])
        if mapped:
            mechanics.extend(mapped)
            continue

        blueprint = DYNAMIC_FEATURE_BLUEPRINTS.get(feature["name"], {})
        module_id = f"generated_{blueprint.get('slug', feature_id)}"
        mechanics.append(module_id)
        requirements[module_id] = {
            "feature_id": feature_id,
            "feature_description": feature["description"],
            "implementation_guidance": blueprint.get(
                "implementation_guidance",
                "Implement only the requested feature and do not duplicate selected modules.",
            ),
            "acceptance_criteria": blueprint.get(
                "acceptance_criteria",
                "The requested behavior is observable, bounded, and safe when dependencies are missing.",
            ),
        }

    return FeatureMechanicPlan(
        game_features=game_features,
        mechanics=list(dict.fromkeys(mechanics)),
        generation_requirements=requirements,
    )


def _mapped_mechanics(name: str, genre: GameGenre, description: str = "") -> tuple[str, ...]:
    if name == "성장":
        return ("experience",) if genre == "뱀서류" else ("stats",)
    if genre == "플랫포머" and name == "사용자 지정 조건":
        normalized = description.replace(" ", "")
        destination_words = ("목적지", "목표지점", "도착점", "스테이지클리어")
        hazard_words = ("장애물", "가시", "함정", "위험", "피해")
        collectible_words = ("보석", "수집물", "아이템을모", "모두모")
        checkpoint_words = ("체크포인트", "저장지점", "부활지점", "리스폰")
        mapped: list[str] = []
        if any(word in normalized for word in hazard_words):
            mapped.append("health_damage")
        if any(word in normalized for word in collectible_words):
            mapped.append("collectible")
        if any(word in normalized for word in checkpoint_words):
            # Checkpoint/respawn actors are assembled with the platformer stage controller.
            # The health module supplies the damage lifecycle they recover from.
            mapped.append("health_damage")
        if any(word in normalized for word in destination_words):
            mapped.append("goal")
        if mapped:
            return tuple(dict.fromkeys(mapped))
    return FEATURE_MODULE_MECHANICS.get(name, ())


def _safe_identifier(value: str, fallback: str) -> str:
    normalized = re.sub(r"[^a-z0-9_]+", "_", value.lower()).strip("_")
    if not normalized or not normalized[0].isalpha():
        return fallback
    return normalized

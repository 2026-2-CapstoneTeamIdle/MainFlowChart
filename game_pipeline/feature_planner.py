"""Map analyzed user features to reusable or dynamically generated mechanics."""

from __future__ import annotations

import re
from dataclasses import dataclass

from mainflow.contracts import FeatureRequirement, GameFeature, GameGenre

FEATURE_MODULE_MECHANICS: dict[str, tuple[str, ...]] = {
    "좌우 이동": ("platformer_movement",),
    "8방향 이동": ("top_down_movement",),
    # Attack delivery is deliberately not mapped. "Automatic attack" says when an attack
    # happens, not whether it is a projectile, orbiting weapon, beam, melee hit, or summon.
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
    custom_features = [feature for feature in features if feature["name"] == "사용자 지정 조건"]
    dependency_closures: dict[str, list[FeatureRequirement]] = {}
    for candidate in features:
        if candidate.get("origin") != "requirement_dependency":
            continue
        for supported_id in candidate.get("supports_feature_ids", []):
            dependency_closures.setdefault(supported_id, []).append(candidate)

    for index, feature in enumerate(features, start=1):
        if _is_superseded_by_specific_requirement(feature, custom_features):
            continue
        feature_id = _safe_identifier(feature["feature_id"], f"feature_{index:02d}")
        game_feature: GameFeature = {
            "feature_id": feature_id,
            "description": feature["description"],
            "required": True,
        }
        for key in (
            "origin",
            "supports_feature_ids",
            "dependency_role",
            "acceptance_criteria",
            "checklist",
        ):
            if key in feature:
                game_feature[key] = feature[key]  # type: ignore[literal-required]
        game_features.append(game_feature)
        mapped = _mapped_mechanics(feature["name"], genre, feature["description"])
        implementation_kind = feature.get("implementation_kind")
        target_mechanics = feature.get("target_mechanics", [])
        if implementation_kind and implementation_kind != "generate_code":
            mechanics.extend(mapped)
            mechanics.extend(target_mechanics)
            continue
        if mapped:
            mechanics.extend(mapped)
            continue

        blueprint = DYNAMIC_FEATURE_BLUEPRINTS.get(feature["name"], {})
        module_id = f"generated_{blueprint.get('slug', feature_id)}"
        mechanics.append(module_id)
        closures = dependency_closures.get(feature["feature_id"], [])
        closure_behaviors = [item["description"] for item in closures]
        closure_acceptance = [
            item["acceptance_criteria"] for item in closures if item.get("acceptance_criteria")
        ]
        must_preserve = "\n".join(dict.fromkeys([feature["description"], *closure_behaviors]))
        acceptance_criteria = "\n".join(
            dict.fromkeys(
                [
                    feature.get("acceptance_criteria")
                    or blueprint.get(
                        "acceptance_criteria",
                        "Every requested cause and effect is executable and observable in Play "
                        "Mode; changing a private variable or logging a message alone does not "
                        "satisfy it.",
                    ),
                    *closure_acceptance,
                ]
            )
        )
        closure_guidance = (
            " Functional closure inferred from the user's request must be implemented in the "
            "same causal flow: " + "; ".join(closure_behaviors)
            if closure_behaviors
            else ""
        )
        requirements[module_id] = {
            "feature_id": feature_id,
            "feature_description": feature["description"],
            "source_text": feature["source_text"],
            "must_preserve": must_preserve,
            "forbidden_substitutions": (
                "Do not replace an explicitly requested actor, attack delivery, trigger, "
                "reward object, collection step, target, or causal order with another mechanic."
            ),
            "implementation_guidance": blueprint.get(
                "implementation_guidance",
                "Implement only the requested feature and do not duplicate selected modules.",
            )
            + closure_guidance,
            "acceptance_criteria": acceptance_criteria,
        }

    return FeatureMechanicPlan(
        game_features=game_features,
        mechanics=list(dict.fromkeys(mechanics)),
        generation_requirements=requirements,
    )


def _is_superseded_by_specific_requirement(
    feature: FeatureRequirement,
    custom_features: list[FeatureRequirement],
) -> bool:
    """Prefer a concrete user mechanic over a broad keyword-derived attack requirement."""

    if feature["name"] not in {"자동 공격", "공격"}:
        return False
    return any(
        custom["source_text"] == feature["source_text"]
        and any(word in custom["description"] for word in ("공격", "피해", "타격"))
        for custom in custom_features
    )


def _mapped_mechanics(name: str, genre: GameGenre, description: str = "") -> tuple[str, ...]:
    if name == "성장":
        return ("experience",) if genre == "뱀서류" else ("stats",)
    if genre == "뱀서류" and name == "사용자 지정 조건":
        normalized = description.replace(" ", "")
        level_up_words = ("레벨이오르면", "레벨업", "경험치를모아")
        choice_words = ("특전3개", "선택지3개", "3가지특전", "하나를선택")
        if any(word in normalized for word in level_up_words) and any(
            word in normalized for word in choice_words
        ):
            return ("experience", "rarity", "upgrade_selection")
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

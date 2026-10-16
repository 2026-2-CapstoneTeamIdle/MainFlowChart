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
        mapped = _mapped_mechanics(feature["name"], genre)
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


def _mapped_mechanics(name: str, genre: GameGenre) -> tuple[str, ...]:
    if name == "성장":
        return ("experience",) if genre == "뱀서류" else ("stats",)
    return FEATURE_MODULE_MECHANICS.get(name, ())


def _safe_identifier(value: str, fallback: str) -> str:
    normalized = re.sub(r"[^a-z0-9_]+", "_", value.lower()).strip("_")
    if not normalized or not normalized[0].isalpha():
        return fallback
    return normalized

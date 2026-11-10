"""Image requirements for scene objects that the Unity assembler actually places.

The genre presets in ``design_catalog`` only list the core character and map
images.  The level plan, however, also places enemies, hazards, collectibles,
checkpoints, a goal and a full-screen background, and without an image request
Unity renders those as flat colored blocks.  This module inspects the level
plan and returns one optional image requirement per placed object category, so
every visible object gets generated art.

Each ``asset_id`` here must stay in sync with ``SceneObjectNames`` in
``unity_template/Assets/GameTemplate/Editor/GeneratedAssetBinder.cs``, which
binds the generated sprite to the scene objects by name.

Descriptions avoid words that ``asset_specs.classify_image_kind`` maps to other
kinds (``배경``, ``스테이지``, ``타일`` ...) unless that kind is intended, and only
the enemy description contains a character keyword so that only enemies get an
animation sprite sheet.
"""

from __future__ import annotations

from typing import cast

from game_pipeline.asset_specs import classify_image_kind
from mainflow.contracts import AssetRequirement, GameSpec, LevelPlan

STAGE_BACKGROUND_ASSET_ID = "stage_background"

# (asset_id, level plan collection, purpose, description)
_PLATFORMER_OBJECT_VISUALS: tuple[tuple[str, str, str, str], ...] = (
    (
        "platformer_enemy",
        "enemies",
        "적",
        "발판 위를 좌우로 순찰하며 플레이어와 부딪히면 피해를 주는 적 캐릭터 스프라이트",
    ),
    (
        "platformer_hazard",
        "hazards",
        "함정",
        "닿으면 피해를 주는 낮고 넓은 가시 함정 오브젝트",
    ),
    (
        "platformer_collectible",
        "collectibles",
        "수집물",
        "획득하면 점수가 오르는 작고 반짝이는 보석 아이템",
    ),
    (
        "platformer_checkpoint",
        "checkpoint",
        "체크포인트",
        "진행 상황을 저장하는 세로로 긴 깃발 기둥",
    ),
)

_PLATFORMER_GOAL = (
    "platformer_goal",
    "골",
    "도달하면 클리어되는 세로로 긴 빛나는 출구 문",
)

_BACKGROUND_DESCRIPTIONS: dict[str, str] = {
    "Platformer": "사이드뷰 플랫포머 뒤에 깔리는 원경 배경 그림, 캐릭터와 발판 없이 풍경만",
    "SurvivorLike": "탑다운 전투 아레나 바닥 배경 그림, 캐릭터 없이 지형만",
    "TowerDefense": "적이 이동하는 전장 바닥 배경 그림, 유닛 없이 지형만",
    "CardGame": "카드 테이블 배경 그림, 카드와 글자 없이 질감만",
}
_DEFAULT_BACKGROUND_DESCRIPTION = "게임 화면 뒤에 깔리는 배경 그림, 캐릭터 없이 풍경만"


def _requirement(asset_id: str, purpose: str, description: str) -> AssetRequirement:
    return cast(
        AssetRequirement,
        {
            "asset_id": asset_id,
            "asset_type": "image",
            "purpose": purpose,
            "description": description,
            # Optional: a failed object image keeps Unity's primitive visual instead of
            # failing the whole run.
            "required": False,
        },
    )


def _archetypes(level_plan: LevelPlan, collection: str) -> list[str]:
    names: list[str] = []
    for zone in level_plan["zones"]:
        if collection == "checkpoint":
            placements = [zone["checkpoint"]] if zone["checkpoint"] is not None else []
        else:
            placements = zone[collection]  # type: ignore[literal-required]
        for placement in placements:
            archetype = str(placement["archetype"]).strip()
            if archetype and archetype not in names:
                names.append(archetype)
    return names


def scene_visual_requirements(
    game_spec: GameSpec,
    level_plan: LevelPlan,
) -> list[AssetRequirement]:
    """Return image requirements for placed scene objects that have no image yet."""

    existing = [item for item in game_spec["asset_requirements"] if item["asset_type"] == "image"]
    existing_ids = {item["asset_id"] for item in existing}
    requirements: list[AssetRequirement] = []

    if game_spec["genre"] == "Platformer":
        for asset_id, collection, purpose, description in _PLATFORMER_OBJECT_VISUALS:
            archetypes = _archetypes(level_plan, collection)
            if not archetypes or asset_id in existing_ids:
                continue
            requirements.append(
                _requirement(asset_id, purpose, f"{description} (종류: {', '.join(archetypes)})")
            )
        goal_id, goal_purpose, goal_description = _PLATFORMER_GOAL
        if goal_id not in existing_ids:
            requirements.append(_requirement(goal_id, goal_purpose, goal_description))

    # Every genre gets a full-screen "Background" object. Genres whose preset already
    # requests a background image (visual novel, raising sim) bind that one instead.
    has_background = any(
        classify_image_kind(item["purpose"], item["description"]) == "background"
        for item in existing
    )
    if not has_background and STAGE_BACKGROUND_ASSET_ID not in existing_ids:
        requirements.append(
            _requirement(
                STAGE_BACKGROUND_ASSET_ID,
                "배경",
                _BACKGROUND_DESCRIPTIONS.get(game_spec["genre"], _DEFAULT_BACKGROUND_DESCRIPTION),
            )
        )
    return requirements


def with_scene_visual_assets(game_spec: GameSpec, level_plan: LevelPlan) -> GameSpec:
    """Return ``game_spec`` with image requirements for every placed object category."""

    additions = scene_visual_requirements(game_spec, level_plan)
    if not additions:
        return game_spec
    return cast(
        GameSpec,
        {
            **game_spec,
            "asset_requirements": [*game_spec["asset_requirements"], *additions],
        },
    )

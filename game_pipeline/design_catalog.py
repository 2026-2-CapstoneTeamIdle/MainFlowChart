"""Genre presets and reusable Unity module planning.

The catalog is deterministic on purpose. An LLM may propose a partial GameSpec,
but the pipeline normalizes it here before any Unity files are generated.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any, cast

from mainflow.contracts import (
    CONTRACT_VERSION,
    AssetRequirement,
    GameFeature,
    GameGenre,
    GameLogicDesign,
    GameSpec,
    GenreProfile,
)

COMMON_MODULES = [
    "game_bootstrap",
    "game_state_store",
    "event_rule_engine",
    "scene_flow_manager",
    "input_adapter",
    "save_system",
    "asset_registry",
    "audio_manager",
    "ui_router",
    "validation_probe",
]

MECHANIC_TO_MODULE = {
    "top_down_movement": "top_down_movement",
    "grid_movement": "grid_movement",
    "collision": "collision_system",
    "map_transition": "map_transition",
    "interaction": "interaction_system",
    "dialogue": "dialogue_runner",
    "choice": "choice_branch_system",
    "branching": "choice_branch_system",
    "flags": "flag_system",
    "multiple_endings": "ending_resolver",
    "relationship": "relationship_system",
    "stats": "stat_system",
    "experience": "experience_system",
    "upgrade_selection": "upgrade_selection_system",
    "rarity": "rarity_system",
    "schedule": "schedule_system",
    "health_damage": "health_damage_system",
    "enemy_spawn": "enemy_spawn_system",
    "chase_ai": "chase_ai_system",
    "auto_target": "auto_target_system",
    "projectile": "projectile_system",
    "inventory": "inventory_system",
    "item_interaction": "item_interaction_system",
    "economy": "economy_system",
    "reward": "reward_system",
    "time_turn": "time_turn_system",
    "farming": "farming_system",
    "npc_schedule": "npc_schedule_system",
    "activity": "activity_system",
}

GENRE_ALIASES: dict[str, GenreProfile] = {
    "Action": "SurvivorLike",
    "RPG": "Adventure",
    "Platformer": "Adventure",
    "Puzzle": "Adventure",
    "Simulation": "RaisingSimulation",
    "SurvivorLike": "SurvivorLike",
    "Adventure": "Adventure",
    "VisualNovel": "VisualNovel",
    "RaisingSimulation": "RaisingSimulation",
    "LifeSimulation": "LifeSimulation",
    "플랫포머": "Adventure",
    "타워 디펜스": "SurvivorLike",
    "카드": "VisualNovel",
    "비주얼 노벨": "VisualNovel",
    "육성 시뮬레이션": "RaisingSimulation",
    "뱀서류": "SurvivorLike",
}


def _feature(feature_id: str, description: str) -> GameFeature:
    return {"feature_id": feature_id, "description": description, "required": True}


def _asset(
    asset_id: str,
    asset_type: str,
    purpose: str,
    description: str,
) -> AssetRequirement:
    return cast(
        AssetRequirement,
        {
            "asset_id": asset_id,
            "asset_type": asset_type,
            "purpose": purpose,
            "description": description,
            "required": True,
        },
    )


GENRE_PRESETS: dict[GenreProfile, GameSpec] = {
    "SurvivorLike": {
        "title": "Survivor-like Prototype",
        "genre": "SurvivorLike",
        "features": [
            _feature("player_movement", "플레이어가 8방향으로 이동한다."),
            _feature("enemy_wave", "적이 지속적으로 생성되어 플레이어를 추적한다."),
            _feature("auto_feather_attack", "날개에서 가까운 적에게 깃털을 자동 발사한다."),
            _feature("level_up", "경험치 획득 시 레벨이 상승한다."),
            _feature("three_upgrade_choices", "레벨업 시 강화 선택지 3개를 표시한다."),
            _feature("upgrade_rarity", "강화에 일반·레어·에픽·전설 등급을 적용한다."),
            _feature("game_over", "플레이어 사망 시 결과와 재시작 UI를 표시한다."),
        ],
        "mechanics": [
            "top_down_movement",
            "health_damage",
            "enemy_spawn",
            "chase_ai",
            "auto_target",
            "projectile",
            "experience",
            "upgrade_selection",
            "rarity",
            "stats",
        ],
        "controls": {"movement": "WASD or arrow keys", "confirm": "Enter"},
        "win_conditions": ["survive_until_time_limit"],
        "lose_conditions": ["player_hp_is_zero"],
        "target_engine": "Unity",
        "asset_requirements": [
            _asset("player_sprite", "image", "플레이어", "날개를 가진 플레이어 스프라이트"),
            _asset("enemy_sprite", "image", "적", "플레이어를 추적하는 적 스프라이트"),
            _asset("feather_projectile", "image", "공격", "날개에서 발사되는 깃털 투사체"),
            _asset("survivor_bgm", "sound", "배경음악", "반복 가능한 전투 배경음악"),
            _asset("feather_attack_sfx", "sound", "공격 효과음", "짧은 깃털 발사 효과음"),
        ],
    },
    "Adventure": {
        "title": "Adventure Prototype",
        "genre": "Adventure",
        "features": [
            _feature("grid_exploration", "플레이어가 타일 맵을 이동하고 충돌한다."),
            _feature("object_interaction", "오브젝트 조사와 NPC 대화를 지원한다."),
            _feature("flag_puzzle", "플래그와 아이템 조건으로 퍼즐을 진행한다."),
            _feature("chase_game_over", "위험 요소가 플레이어를 추격하고 접촉 시 게임오버된다."),
        ],
        "mechanics": [
            "grid_movement",
            "collision",
            "map_transition",
            "interaction",
            "dialogue",
            "choice",
            "flags",
            "inventory",
            "item_interaction",
            "chase_ai",
        ],
        "controls": {"movement": "arrow keys", "interact": "Space", "cancel": "Escape"},
        "win_conditions": ["required_puzzle_flags_are_complete"],
        "lose_conditions": ["player_is_caught"],
        "target_engine": "Unity",
        "asset_requirements": [
            _asset("adventure_player", "image", "플레이어", "4방향 이동 캐릭터 스프라이트"),
            _asset("adventure_tileset", "image", "맵", "실내 탐색용 타일셋"),
            _asset("adventure_bgm", "sound", "배경음악", "긴장감 있는 반복 배경음악"),
            _asset("interaction_sfx", "sound", "상호작용", "조사 및 아이템 획득 효과음"),
        ],
    },
    "VisualNovel": {
        "title": "Visual Novel Prototype",
        "genre": "VisualNovel",
        "features": [
            _feature("dialogue_sequence", "화자와 대사를 순서대로 표시한다."),
            _feature("choice_branch", "선택에 따라 시나리오와 상태가 분기된다."),
            _feature("affection", "선택 결과로 호감도가 변한다."),
            _feature("two_endings", "조건에 따라 최소 2개의 엔딩을 제공한다."),
            _feature("dialogue_log", "지나간 대화를 확인할 수 있다."),
        ],
        "mechanics": [
            "dialogue",
            "choice",
            "branching",
            "flags",
            "relationship",
            "multiple_endings",
        ],
        "controls": {"advance": "Space or left click", "menu": "Escape"},
        "win_conditions": ["an_ending_is_reached"],
        "lose_conditions": [],
        "target_engine": "Unity",
        "asset_requirements": [
            _asset("novel_background", "image", "배경", "주요 장면 배경 이미지"),
            _asset("novel_character", "image", "캐릭터", "표정 변형이 가능한 캐릭터 초상화"),
            _asset("novel_bgm", "sound", "배경음악", "대화 장면용 반복 배경음악"),
            _asset("choice_sfx", "sound", "UI", "선택지 결정 효과음"),
        ],
    },
    "RaisingSimulation": {
        "title": "Raising Simulation Prototype",
        "genre": "RaisingSimulation",
        "features": [
            _feature("calendar_turn", "행동 선택 후 날짜 또는 턴이 진행된다."),
            _feature("training_stats", "훈련·공부·휴식으로 능력치와 피로도가 변한다."),
            _feature("conditional_events", "능력치와 관계 조건에 따라 이벤트가 발생한다."),
            _feature("result_endings", "기간 종료 시 상태에 따라 최소 2개의 엔딩을 판정한다."),
        ],
        "mechanics": [
            "time_turn",
            "stats",
            "activity",
            "schedule",
            "relationship",
            "economy",
            "flags",
            "multiple_endings",
        ],
        "controls": {"select": "left click", "cancel": "Escape"},
        "win_conditions": ["training_period_is_complete"],
        "lose_conditions": ["critical_resource_is_depleted"],
        "target_engine": "Unity",
        "asset_requirements": [
            _asset("raising_character", "image", "캐릭터", "육성 대상 캐릭터 초상화"),
            _asset("raising_room", "image", "배경", "상태 화면용 방 배경"),
            _asset("raising_bgm", "sound", "배경음악", "일상적인 반복 배경음악"),
            _asset("activity_sfx", "sound", "행동", "행동 완료 효과음"),
        ],
    },
    "LifeSimulation": {
        "title": "Life Simulation Prototype",
        "genre": "LifeSimulation",
        "features": [
            _feature("farm_cycle", "밭 갈기·파종·물주기·성장·수확을 지원한다."),
            _feature("day_cycle", "게임 내 시간과 날짜가 진행된다."),
            _feature("inventory_shop", "아이템 보관과 구매·판매를 지원한다."),
            _feature("npc_relationship", "NPC 대화와 호감도 변화를 지원한다."),
            _feature("multiple_maps", "농장·집·상점 사이를 이동한다."),
        ],
        "mechanics": [
            "top_down_movement",
            "collision",
            "map_transition",
            "interaction",
            "time_turn",
            "farming",
            "inventory",
            "item_interaction",
            "economy",
            "npc_schedule",
            "dialogue",
            "relationship",
        ],
        "controls": {"movement": "WASD", "use_tool": "left click", "interact": "Space"},
        "win_conditions": ["prototype_goal_is_complete"],
        "lose_conditions": [],
        "target_engine": "Unity",
        "asset_requirements": [
            _asset("farmer_player", "image", "플레이어", "4방향 농부 캐릭터 스프라이트"),
            _asset("farm_tileset", "image", "맵", "농장·집·상점용 타일셋"),
            _asset("crop_sprites", "image", "작물", "성장 단계별 작물 스프라이트"),
            _asset("life_bgm", "sound", "배경음악", "편안한 반복 배경음악"),
            _asset("harvest_sfx", "sound", "수확", "짧은 수확 효과음"),
        ],
    },
}


def _unique_strings(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value.strip()))


def _normalize_features(value: object, defaults: list[GameFeature]) -> list[GameFeature]:
    if value is None:
        return deepcopy(defaults)
    if not isinstance(value, list):
        raise TypeError("game_spec.features must be a list")
    features: list[GameFeature] = []
    for index, item in enumerate(value):
        if isinstance(item, str):
            features.append(_feature(f"custom_feature_{index + 1}", item))
        elif isinstance(item, Mapping):
            feature_id = item.get("feature_id")
            description = item.get("description")
            if not isinstance(feature_id, str) or not feature_id.strip():
                raise ValueError("Each feature requires a non-empty feature_id")
            if not isinstance(description, str) or not description.strip():
                raise ValueError("Each feature requires a non-empty description")
            features.append(
                {
                    "feature_id": feature_id,
                    "description": description,
                    "required": bool(item.get("required", True)),
                }
            )
        else:
            raise TypeError("Each feature must be a string or object")
    if len({item["feature_id"] for item in features}) != len(features):
        raise ValueError("game_spec feature_id values must be unique")
    merged = {item["feature_id"]: deepcopy(item) for item in defaults}
    merged.update({item["feature_id"]: item for item in features})
    return list(merged.values())


def _normalize_assets(
    value: object,
    defaults: list[AssetRequirement],
) -> list[AssetRequirement]:
    if value is None:
        return deepcopy(defaults)
    if not isinstance(value, list):
        raise TypeError("game_spec.asset_requirements must be a list")
    assets: list[AssetRequirement] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise TypeError("Each asset requirement must be an object")
        asset_id = item.get("asset_id")
        asset_type = item.get("asset_type")
        purpose = item.get("purpose")
        description = item.get("description")
        if not isinstance(asset_id, str) or not asset_id.strip():
            raise ValueError("Each asset requirement needs a non-empty asset_id")
        if asset_type not in ("image", "sound"):
            raise ValueError(f"Unsupported asset_type for {asset_id}: {asset_type}")
        if not isinstance(purpose, str) or not purpose.strip():
            raise ValueError(f"Asset {asset_id} requires a purpose")
        if not isinstance(description, str) or not description.strip():
            raise ValueError(f"Asset {asset_id} requires a description")
        assets.append(
            cast(
                AssetRequirement,
                {
                    "asset_id": asset_id,
                    "asset_type": asset_type,
                    "purpose": purpose,
                    "description": description,
                    "required": bool(item.get("required", True)),
                },
            )
        )
    if len({item["asset_id"] for item in assets}) != len(assets):
        raise ValueError("game_spec asset_id values must be unique")
    merged = {item["asset_id"]: deepcopy(item) for item in defaults}
    merged.update({item["asset_id"]: item for item in assets})
    return list(merged.values())


def _string_list(
    value: object,
    field_name: str,
    defaults: list[str],
    *,
    merge_defaults: bool = False,
) -> list[str]:
    if value is None:
        return list(defaults)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"game_spec.{field_name} must be a list of strings")
    supplied = cast(list[str], value)
    return _unique_strings(defaults + supplied if merge_defaults else supplied)


def normalize_game_spec(
    input_genre: GameGenre,
    overrides: Mapping[str, Any] | None = None,
) -> GameSpec:
    """Return a complete, validated GameSpec from a genre and optional overrides."""

    requested_profile = overrides.get("genre") if overrides else None
    if requested_profile is not None and requested_profile not in GENRE_PRESETS:
        raise ValueError(f"Unsupported game_spec.genre: {requested_profile}")
    profile = cast(
        GenreProfile,
        requested_profile or GENRE_ALIASES[input_genre],
    )
    preset = GENRE_PRESETS[profile]
    override = overrides or {}

    title = override.get("title", preset["title"])
    if not isinstance(title, str) or not title.strip():
        raise ValueError("game_spec.title must be a non-empty string")

    target_engine = override.get("target_engine", "Unity")
    if target_engine != "Unity":
        raise ValueError("The game pipeline currently supports only Unity")

    controls_value = override.get("controls", {})
    if not isinstance(controls_value, Mapping) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in controls_value.items()
    ):
        raise ValueError("game_spec.controls must map strings to strings")

    return {
        "title": title,
        "genre": profile,
        "features": _normalize_features(override.get("features"), preset["features"]),
        "mechanics": _string_list(
            override.get("mechanics"),
            "mechanics",
            preset["mechanics"],
            merge_defaults=True,
        ),
        "controls": {**preset["controls"], **dict(controls_value)},
        "win_conditions": _string_list(
            override.get("win_conditions"),
            "win_conditions",
            preset["win_conditions"],
        ),
        "lose_conditions": _string_list(
            override.get("lose_conditions"),
            "lose_conditions",
            preset["lose_conditions"],
        ),
        "target_engine": "Unity",
        "asset_requirements": _normalize_assets(
            override.get("asset_requirements"),
            preset["asset_requirements"],
        ),
    }


def build_game_logic_design(game_spec: GameSpec) -> GameLogicDesign:
    """Map normalized mechanics to the reusable Unity module catalog."""

    genre_modules = _unique_strings(
        [
            MECHANIC_TO_MODULE[mechanic]
            for mechanic in game_spec["mechanics"]
            if mechanic in MECHANIC_TO_MODULE
        ]
    )
    unsupported = [
        mechanic for mechanic in game_spec["mechanics"] if mechanic not in MECHANIC_TO_MODULE
    ]
    return {
        "contract_version": CONTRACT_VERSION,
        "design_id": f"{game_spec['genre'].lower()}-game-design",
        "game_spec": game_spec,
        "common_modules": list(COMMON_MODULES),
        "genre_modules": genre_modules,
        "selected_modules": _unique_strings(COMMON_MODULES + genre_modules),
        "unsupported_mechanics": unsupported,
    }

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
    Viewpoint,
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
    "platformer_movement": "platformer_movement",
    "collectible": "collectible_system",
    "goal": "goal_system",
    "wave_spawn": "wave_spawner",
    "tower_targeting": "tower_targeting_system",
    "base_defense": "base_defense_system",
    "deck": "deck_system",
    "turn": "turn_system",
    "card_resource": "card_resource_system",
    "card_effect": "card_effect_system",
    "top_down_movement": "top_down_movement",
    "dialogue": "dialogue_runner",
    "choice": "choice_branch_system",
    "branching": "choice_branch_system",
    "flags": "flag_system",
    "multiple_endings": "ending_resolver",
    "raising_endings": "raising_ending_resolver",
    "stats": "stat_system",
    "experience": "experience_system",
    "upgrade_selection": "upgrade_selection_system",
    "rarity": "rarity_system",
    "schedule": "schedule_system",
    "health_damage": "health_damage_system",
    "enemy_spawn": "enemy_spawn_system",
    "chase_ai": "enemy_spawn_system",
    "auto_target": "auto_target_system",
    "projectile": "projectile_system",
    "economy": "economy_system",
    "time_turn": "time_turn_system",
    "activity": "activity_system",
}

GENRE_ALIASES: dict[str, GenreProfile] = {
    "Action": "SurvivorLike",
    "RPG": "Platformer",
    "Platformer": "Platformer",
    "Puzzle": "Platformer",
    "Simulation": "RaisingSimulation",
    "SurvivorLike": "SurvivorLike",
    "TowerDefense": "TowerDefense",
    "CardGame": "CardGame",
    "VisualNovel": "VisualNovel",
    "RaisingSimulation": "RaisingSimulation",
    "플랫포머": "Platformer",
    "타워 디펜스": "TowerDefense",
    "카드": "CardGame",
    "비주얼 노벨": "VisualNovel",
    "육성 시뮬레이션": "RaisingSimulation",
    "뱀서류": "SurvivorLike",
}

SUPPORTED_VIEWPOINTS: set[str] = {"사이드뷰", "탑다운", "쿼터뷰", "고정 화면"}


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
        "viewpoint": "탑다운",
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
            "projectile",
            "auto_target",
            "experience",
            "rarity",
            "upgrade_selection",
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
    "Platformer": {
        "title": "Platformer Prototype",
        "genre": "Platformer",
        "viewpoint": "사이드뷰",
        "features": [
            _feature("side_scroll_movement", "플레이어가 좌우로 이동하고 점프한다."),
            _feature("platform_collision", "바닥과 발판에 충돌하고 낙하를 처리한다."),
            _feature("collectibles", "수집물을 획득하고 진행도를 갱신한다."),
            _feature("stage_goal", "목표 지점 도달 시 스테이지를 완료한다."),
        ],
        "mechanics": [
            "platformer_movement",
            "health_damage",
            "collectible",
            "goal",
        ],
        "controls": {"movement": "A/D or arrow keys", "jump": "Space"},
        "win_conditions": ["stage_goal_is_reached"],
        "lose_conditions": ["player_hp_is_zero_or_falls"],
        "target_engine": "Unity",
        "asset_requirements": [
            _asset("platformer_player", "image", "플레이어", "좌우 이동과 점프 캐릭터 스프라이트"),
            _asset("platformer_tileset", "image", "맵", "발판과 지형 타일셋"),
            _asset("platformer_bgm", "sound", "배경음악", "스테이지 반복 배경음악"),
            _asset("jump_sfx", "sound", "점프", "짧은 점프 효과음"),
        ],
    },
    "TowerDefense": {
        "title": "Tower Defense Prototype",
        "genre": "TowerDefense",
        "viewpoint": "탑다운",
        "features": [
            _feature("enemy_waves", "적 웨이브가 경로를 따라 순차적으로 등장한다."),
            _feature("tower_attack", "타워가 범위 내 적을 자동으로 공격한다."),
            _feature("tower_economy", "적 처치 보상으로 타워를 배치하거나 강화한다."),
            _feature("base_lives", "적이 종점에 도달하면 기지 체력이 감소한다."),
        ],
        "mechanics": [
            "wave_spawn",
            "projectile",
            "tower_targeting",
            "health_damage",
            "economy",
            "base_defense",
        ],
        "controls": {"select": "left click", "cancel": "right click or Escape"},
        "win_conditions": ["all_waves_are_cleared"],
        "lose_conditions": ["base_lives_are_zero"],
        "target_engine": "Unity",
        "asset_requirements": [
            _asset("tower_sprite", "image", "타워", "공격 타워 스프라이트"),
            _asset("tower_enemy", "image", "적", "경로를 이동하는 적 스프라이트"),
            _asset("tower_bgm", "sound", "배경음악", "전투 웨이브 반복 배경음악"),
            _asset("tower_attack_sfx", "sound", "공격", "타워 발사 효과음"),
        ],
    },
    "CardGame": {
        "title": "Card Game Prototype",
        "genre": "CardGame",
        "viewpoint": "고정 화면",
        "features": [
            _feature("deck_and_hand", "덱을 섞고 카드를 뽑아 손패를 구성한다."),
            _feature("turn_progression", "플레이어와 상대의 턴을 교대한다."),
            _feature("card_cost", "자원을 지불해 카드를 사용한다."),
            _feature("card_effect", "카드 효과를 대상과 게임 상태에 적용한다."),
        ],
        "mechanics": ["deck", "turn", "card_resource", "card_effect", "health_damage"],
        "controls": {"select": "left click", "cancel": "right click or Escape"},
        "win_conditions": ["opponent_hp_is_zero"],
        "lose_conditions": ["player_hp_is_zero"],
        "target_engine": "Unity",
        "asset_requirements": [
            _asset("card_frame", "image", "카드 UI", "카드 테두리와 배경 이미지"),
            _asset("card_art", "image", "카드 일러스트", "효과를 표현하는 카드 이미지"),
            _asset("card_bgm", "sound", "배경음악", "턴 진행용 반복 배경음악"),
            _asset("card_play_sfx", "sound", "카드 사용", "카드를 사용할 때의 효과음"),
        ],
    },
    "VisualNovel": {
        "title": "Visual Novel Prototype",
        "genre": "VisualNovel",
        "viewpoint": "고정 화면",
        "features": [
            _feature("dialogue_sequence", "화자와 대사를 순서대로 표시한다."),
            _feature("choice_branch", "선택에 따라 시나리오와 상태가 분기된다."),
            _feature("affection", "선택 결과로 호감도가 변한다."),
            _feature("two_endings", "조건에 따라 최소 2개의 엔딩을 제공한다."),
            _feature("dialogue_log", "지나간 대화를 확인할 수 있다."),
        ],
        "mechanics": [
            "flags",
            "dialogue",
            "choice",
            "branching",
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
        "viewpoint": "고정 화면",
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
            "economy",
            "raising_endings",
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

    viewpoint = override.get("viewpoint", preset["viewpoint"])
    if viewpoint not in SUPPORTED_VIEWPOINTS:
        raise ValueError(f"Unsupported game_spec.viewpoint: {viewpoint}")

    controls_value = override.get("controls", {})
    if not isinstance(controls_value, Mapping) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in controls_value.items()
    ):
        raise ValueError("game_spec.controls must map strings to strings")

    return {
        "title": title,
        "genre": profile,
        "viewpoint": cast(Viewpoint, viewpoint),
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

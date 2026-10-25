"""Vertical-slice game design contracts and safe deterministic fallbacks.

The v2 documents deliberately separate direction, systems, content, level,
balance, presentation, and validation.  A small local model can improve one
document at a time without being asked to invent a complete Unity game in one
response.  The deterministic platformer plan remains the safety net and is
always traversable under the movement limits recorded in the plan.
"""

from __future__ import annotations

import hashlib
import random
from collections import Counter
from itertools import pairwise

from mainflow.contracts import (
    BalancePlan,
    ContentPlan,
    DesignV2Bundle,
    GameDirectorDesign,
    GameSpec,
    LevelPlacement,
    LevelPlan,
    LevelPlatform,
    LevelZone,
    PresentationPlan,
    SystemDesign,
    ValidationPlan,
)


def build_design_v2(
    game_spec: GameSpec,
    design_intent: str,
    *,
    variation_seed: str = "",
) -> DesignV2Bundle:
    """Build a complete, executable design bundle.

    Platformer is the first vertical-slice profile. Other genres receive a
    conservative one-zone plan so the shared contract can be extended without
    changing downstream file names.
    """

    intent = design_intent.strip() or "장르의 핵심 루프를 3~5분 동안 체험하는 게임"
    image_ids = [
        item["asset_id"]
        for item in game_spec["asset_requirements"]
        if item["asset_type"] == "image"
    ]
    sound_ids = [
        item["asset_id"]
        for item in game_spec["asset_requirements"]
        if item["asset_type"] == "sound"
    ]
    game_design = _game_design(game_spec, intent)
    system_design = _system_design(game_spec)
    level_plan = (
        _platformer_level_plan(game_spec, intent, variation_seed=variation_seed)
        if game_spec["genre"] == "Platformer"
        else _generic_level_plan(game_spec)
    )
    content_plan = _content_plan(game_spec, level_plan, intent)
    balance_plan = _balance_plan(game_spec)
    presentation_plan: PresentationPlan = {
        "plan_version": "2.0.0",
        "ui_screens": ["hud", "pause", "stage_result", "failure"],
        "state_transitions": [
            "ready -> playing",
            "playing -> checkpoint",
            "playing -> failed",
            "playing -> cleared",
        ],
        "feedback_cues": [
            {
                "cue_id": "player_hit",
                "trigger": "player damaged",
                "visual_feedback": "짧은 적색 플래시와 카메라 흔들림",
                "audio_asset_id": sound_ids[-1] if sound_ids else "",
            },
            {
                "cue_id": "collectible_pickup",
                "trigger": "collectible acquired",
                "visual_feedback": "획득 위치 팝과 HUD 수치 갱신",
                "audio_asset_id": sound_ids[-1] if sound_ids else "",
            },
            {
                "cue_id": "checkpoint_reached",
                "trigger": "checkpoint activated",
                "visual_feedback": "체크포인트 색상 변화와 안내 문구",
                "audio_asset_id": sound_ids[-1] if sound_ids else "",
            },
        ],
        "camera_effects": ["player follow", "hit shake", "goal emphasis"],
        "particle_requests": ["landing dust", "pickup burst", "checkpoint pulse"],
        "animation_requests": ["idle", "run", "jump", "fall", "hit"],
        "required_image_asset_ids": image_ids,
        "required_sound_asset_ids": sound_ids,
    }
    validation_plan = _validation_plan(game_spec, level_plan)
    return {
        "game_design": game_design,
        "system_design": system_design,
        "content_plan": content_plan,
        "level_plan": level_plan,
        "balance_plan": balance_plan,
        "presentation_plan": presentation_plan,
        "validation_plan": validation_plan,
    }


def validate_design_v2(bundle: DesignV2Bundle) -> None:
    """Reject plans that cannot produce the promised vertical slice."""

    if bundle["game_design"]["target_play_minutes"] < 3:
        raise ValueError("target_play_minutes must be at least 3")
    level = bundle["level_plan"]
    if level["genre"] == "Platformer":
        if len(level["zones"]) < 3:
            raise ValueError("Platformer level_plan requires at least three zones")
        if {zone["purpose"] for zone in level["zones"]} != {
            "tutorial",
            "challenge",
            "mastery",
        }:
            raise ValueError("Platformer zones must cover tutorial, challenge, and mastery")
        _validate_platformer_route(level)
        content = bundle["content_plan"]
        for category, collection in (
            ("enemies", "enemies"),
            ("obstacles", "hazards"),
            ("rewards", "collectibles"),
        ):
            for definition in content[category]:  # type: ignore[literal-required]
                actual = _count_placements(level, collection, definition["content_id"])
                if actual != definition["count"]:
                    raise ValueError(
                        f"{definition['content_id']} expects {definition['count']} placements, "
                        f"found {actual}"
                    )
    if level["genre"] == "Platformer":
        scenario_ids = {
            scenario["scenario_id"] for scenario in bundle["validation_plan"]["scenarios"]
        }
        required_scenarios = {"start_to_goal", "checkpoint_recovery", "feature_binding"}
        if scenario_ids != required_scenarios:
            raise ValueError(
                "validation_plan must contain exactly the executable platformer scenarios"
            )
    elif len(bundle["validation_plan"]["scenarios"]) < 3:
        raise ValueError("validation_plan requires at least three scenarios")
    presentation = bundle["presentation_plan"]
    if "hud" not in presentation["ui_screens"]:
        raise ValueError("presentation_plan requires a HUD")
    cue_ids = {cue["cue_id"] for cue in presentation["feedback_cues"]}
    required_cues = {"player_hit", "collectible_pickup", "checkpoint_reached"}
    if not cue_ids.issuperset(required_cues):
        raise ValueError("presentation_plan is missing required gameplay feedback cues")
    if "hit shake" not in presentation["camera_effects"]:
        raise ValueError("presentation_plan requires hit shake feedback")


def _game_design(game_spec: GameSpec, intent: str) -> GameDirectorDesign:
    return {
        "design_version": "2.0.0",
        "title": game_spec["title"],
        "player_experience": intent,
        "target_play_minutes": 4,
        "differentiators": [
            "요청 기능을 진행 필수 동작으로 사용",
            "구역마다 새 규칙을 소개하고 마지막에 조합",
            "실패 지점과 보상을 가까이 배치해 즉시 재도전",
        ],
        "experience_curve": {
            "opening": "안전한 공간에서 이동과 핵심 기능을 한 번씩 학습",
            "midgame": "적·함정·수집물을 섞어 기능을 응용",
            "endgame": "앞서 배운 기능을 연속 사용해 목표에 도달",
        },
        "win_conditions": list(game_spec["win_conditions"]),
        "lose_conditions": list(game_spec["lose_conditions"]),
    }


def _system_design(game_spec: GameSpec) -> SystemDesign:
    abilities = [feature["description"] for feature in game_spec["features"]]
    return {
        "design_version": "2.0.0",
        "player_states": ["ready", "moving", "airborne", "hurt", "dead", "cleared"],
        "player_abilities": abilities,
        "enemy_states": ["idle", "patrol", "chase", "attack", "defeated"],
        "combat_formulas": [
            "final_damage = max(1, attack - defense)",
            "invulnerability_seconds = 0.75 after player damage",
        ],
        "resources": ["health", "collectibles", "checkpoint progress"],
        "progression": ["zone completion", "checkpoint activation", "goal unlock"],
        "save_data": ["last checkpoint", "collected ids", "best clear time"],
        "event_connections": [
            {
                "event_id": "collectible_acquired",
                "producer": "collectible",
                "consumers": ["hud", "goal_rule", "feedback"],
                "payload": ["collectible_id", "current_count"],
            },
            {
                "event_id": "checkpoint_activated",
                "producer": "checkpoint",
                "consumers": ["respawn", "hud", "save"],
                "payload": ["checkpoint_id", "position"],
            },
        ],
        "stats": [
            {"stat_id": "player_health", "initial": 3, "minimum": 1, "maximum": 8, "unit": "hit"},
            {"stat_id": "move_speed", "initial": 7, "minimum": 4, "maximum": 12, "unit": "units/s"},
            {
                "stat_id": "jump_height",
                "initial": 2.4,
                "minimum": 1.8,
                "maximum": 3.5,
                "unit": "units",
            },
        ],
    }


def _content_plan(game_spec: GameSpec, level_plan: LevelPlan, intent: str) -> ContentPlan:
    if game_spec["genre"] == "Platformer":
        enemy_counts = _placement_counts(level_plan, "enemies")
        obstacle_counts = _placement_counts(level_plan, "hazards")
        reward_counts = _placement_counts(level_plan, "collectibles")
        enemy_profiles = {
            "patrol_enemy": (1, 1.8, 1, 1.5, "이동 타이밍 학습"),
            "fast_patrol_enemy": (1, 3.0, 1, 2.0, "빠른 대응과 이동 기능 사용 유도"),
            "armored_patrol_enemy": (3, 1.1, 2, 1.2, "응용 구간의 회피 경로 압박"),
        }
        obstacle_profiles = {
            "floor_spike": (1, 0.3, "점프 정확도 검사"),
            "timed_spike": (1, 0.2, "이동 타이밍과 정지 판단 검사"),
            "damage_orb": (2, 0.1, "공중 이동 경로 제한"),
        }
        reward_profiles = {
            "route_collectible": (1, "주 진행 경로 유도"),
            "bonus_collectible": (3, "위험한 선택 경로에 추가 보상 제공"),
        }
        return {
            "plan_version": "2.0.0",
            "enemies": [
                {
                    "content_id": content_id,
                    "role": f"{role}: {intent[:36]}",
                    "count": count,
                    "stats": [
                        {"stat_id": "health", "value": profile[0]},
                        {"stat_id": "speed", "value": profile[1]},
                        {"stat_id": "contact_damage", "value": profile[2]},
                        {"stat_id": "patrol_range", "value": profile[3]},
                    ],
                    "behaviors": ["patrol platform", "turn at edge", "damage on contact"],
                }
                for content_id, count in enemy_counts.items()
                for profile in [enemy_profiles[content_id]]
                for role in [profile[4]]
            ],
            "obstacles": [
                {
                    "content_id": content_id,
                    "role": role,
                    "count": count,
                    "stats": [
                        {"stat_id": "damage", "value": profile[0]},
                        {"stat_id": "reset_delay", "value": profile[1]},
                    ],
                    "behaviors": ["damage on contact", "respawn at checkpoint"],
                }
                for content_id, count in obstacle_counts.items()
                for profile in [obstacle_profiles[content_id]]
                for role in [profile[2]]
            ],
            "rewards": [
                {
                    "content_id": content_id,
                    "role": profile[1],
                    "count": count,
                    "stats": [{"stat_id": "score", "value": profile[0]}],
                    "behaviors": ["pickup", "bonus feedback", "update hud"],
                }
                for content_id, count in reward_counts.items()
                for profile in [reward_profiles[content_id]]
            ],
            "stages": [zone["title"] for zone in level_plan["zones"]],
            "final_goal": f"필수 보상을 획득하고 {intent[:48]}의 최종 목표에 도달",
        }
    return {
        "plan_version": "2.0.0",
        "enemies": [],
        "obstacles": [],
        "rewards": [],
        "stages": ["introduction", "core challenge", "result"],
        "final_goal": game_spec["win_conditions"][0],
    }


def _platform(
    platform_id: str,
    x: float,
    y: float,
    width: float,
    role: str = "landing",
) -> LevelPlatform:
    return {
        "platform_id": platform_id,
        "role": role,  # type: ignore[typeddict-item]
        "x": x,
        "y": y,
        "width": width,
        "height": 0.5,
    }


def _placement(placement_id: str, archetype: str, x: float, y: float) -> LevelPlacement:
    return {
        "placement_id": placement_id,
        "archetype": archetype,
        "x": x,
        "y": y,
    }


def _platformer_level_plan(
    game_spec: GameSpec,
    intent: str,
    *,
    variation_seed: str = "",
) -> LevelPlan:
    """Create a stable but request-specific, traversable platformer route."""

    seed = int(
        hashlib.sha256(
            (
                f"platformer-v2|{game_spec['title']}|{intent}|"
                f"{'|'.join(game_spec['mechanics'])}|variation:{variation_seed}"
            ).encode()
        ).hexdigest()[:16],
        16,
    )
    rng = random.Random(seed)
    mechanics = list(dict.fromkeys(game_spec["mechanics"]))
    if not mechanics:
        mechanics = ["move", "jump"]
    zone_count = 3 + rng.randrange(3)
    purposes = ["tutorial", *("challenge" for _ in range(zone_count - 2)), "mastery"]
    theme_words = [word for word in intent.replace(",", " ").split() if len(word) > 1]
    platform_groups: list[list[LevelPlatform]] = []
    cursor_x = -18.0
    previous_width = 3.2
    previous_y = -2.35
    platform_index = 0
    for zone_index in range(zone_count):
        group: list[LevelPlatform] = []
        count = 4 + rng.randrange(3)
        for local_index in range(count):
            width = round(rng.uniform(2.5, 3.6), 2)
            if platform_index == 0:
                x = cursor_x
            else:
                gap = rng.uniform(0.35, 1.05)
                x = cursor_x + previous_width / 2 + width / 2 + gap
            step = rng.uniform(-1.0, 0.9)
            y = round(max(-2.6, min(1.4, previous_y + step)), 2)
            role = (
                "goal" if zone_index == zone_count - 1 and local_index == count - 1 else "landing"
            )
            platform_index += 1
            group.append(_platform(f"route_{platform_index}", round(x, 2), y, width, role))
            cursor_x, previous_width, previous_y = x, width, y
        platform_groups.append(group)

    zones: list[LevelZone] = []
    hazard_index = 0
    enemy_index = 0
    collectible_index = 0
    checkpoint_index = 0
    for zone_index, (purpose, platforms) in enumerate(zip(purposes, platform_groups, strict=True)):
        introduced_count = max(1, round(len(mechanics) * (zone_index + 1) / zone_count))
        required_mechanics = mechanics if purpose == "mastery" else mechanics[:introduced_count]
        hazards: list[LevelPlacement] = []
        enemies: list[LevelPlacement] = []
        collectibles: list[LevelPlacement] = []
        danger_count = 0 if purpose == "tutorial" else 1 + min(2, zone_index)
        for danger_offset in range(danger_count):
            target = platforms[min(len(platforms) - 1, danger_offset + 1)]
            hazard_index += 1
            hazard_kind = ("floor_spike", "timed_spike", "damage_orb")[
                (zone_index + danger_offset + seed) % 3
            ]
            hazard_y = -3.35 if hazard_kind != "damage_orb" else target["y"] + 1.15
            hazards.append(
                _placement(f"hazard_{hazard_index}", hazard_kind, target["x"] + 0.45, hazard_y)
            )
        enemy_count = 0 if purpose == "tutorial" else 1 + (zone_index % 2)
        for enemy_offset in range(enemy_count):
            target = platforms[-(enemy_offset + 2)]
            enemy_index += 1
            enemy_kind = ("patrol_enemy", "fast_patrol_enemy", "armored_patrol_enemy")[
                min(2, zone_index + enemy_offset - 1)
            ]
            enemies.append(
                _placement(f"enemy_{enemy_index}", enemy_kind, target["x"], target["y"] + 0.65)
            )
        reward_targets = platforms[::2]
        if purpose == "mastery" and reward_targets and reward_targets[-1] is platforms[-1]:
            reward_targets = reward_targets[:-1]
        for reward_offset, target in enumerate(reward_targets):
            collectible_index += 1
            reward_kind = (
                "bonus_collectible"
                if reward_offset == len(reward_targets) - 1 and purpose != "tutorial"
                else "route_collectible"
            )
            collectibles.append(
                _placement(
                    f"collectible_{collectible_index}",
                    reward_kind,
                    target["x"],
                    target["y"] + 0.9,
                )
            )
        checkpoint = None
        if purpose != "mastery":
            checkpoint_index += 1
            checkpoint_platform = platforms[-1]
            checkpoint = _placement(
                f"checkpoint_{checkpoint_index}",
                "checkpoint",
                checkpoint_platform["x"],
                checkpoint_platform["y"] + 1.15,
            )
        title_word = theme_words[zone_index % len(theme_words)] if theme_words else "핵심"
        start_x = round(platforms[0]["x"] - platforms[0]["width"] / 2 - 0.8, 2)
        end_x = round(platforms[-1]["x"] + platforms[-1]["width"] / 2 + 0.8, 2)
        zones.append(
            {
                "zone_id": f"{purpose}_{zone_index + 1}",
                "title": f"{title_word} {purpose} 구역",
                "purpose": purpose,  # type: ignore[typeddict-item]
                "challenge": f"{', '.join(required_mechanics)}를 사용해 {title_word} 도전을 통과",
                "reward": "체크포인트와 진행 보상" if checkpoint else "목표 문 개방과 클리어",
                "difficulty": zone_index + 1,
                "required_mechanics": required_mechanics,
                "start_x": start_x,
                "end_x": end_x,
                "checkpoint": checkpoint,
                "platforms": platforms,
                "hazards": hazards,
                "enemies": enemies,
                "collectibles": collectibles,
            }
        )

    first_platform = platform_groups[0][0]
    final_platform = platform_groups[-1][-1]
    goal_x = final_platform["x"] + final_platform["width"] * 0.5 - 0.5
    return {
        "plan_version": "2.0.0",
        "genre": "Platformer",
        "player_spawn": _placement(
            "player_spawn", "player", first_platform["x"], first_platform["y"] + 0.95
        ),
        "goal": _placement("stage_goal", "goal", goal_x, final_platform["y"] + 1.25),
        "zones": zones,
        "safe_start_seconds": round(rng.uniform(5.0, 8.0), 2),
        "camera_orthographic_size": round(rng.uniform(5.0, 6.2), 2),
        "max_horizontal_gap": 1.35,
        "max_step_up": 1.15,
        "minimum_landing_width": 2.4,
    }


def _placement_counts(level_plan: LevelPlan, collection: str) -> Counter[str]:
    return Counter(
        placement["archetype"]
        for zone in level_plan["zones"]
        for placement in zone[collection]  # type: ignore[literal-required]
    )


def _generic_level_plan(game_spec: GameSpec) -> LevelPlan:
    return {
        "plan_version": "2.0.0",
        "genre": game_spec["genre"],
        "player_spawn": _placement("player_spawn", "player", 0, 0),
        "goal": _placement("stage_goal", "goal", 8, 0),
        "zones": [],
        "safe_start_seconds": 5.0,
        "camera_orthographic_size": 6.0,
        "max_horizontal_gap": 1.4,
        "max_step_up": 1.15,
        "minimum_landing_width": 2.4,
    }


def _balance_plan(game_spec: GameSpec) -> BalancePlan:
    return {
        "plan_version": "2.0.0",
        "stats": [
            {"stat_id": "player_health", "initial": 3, "minimum": 1, "maximum": 8, "unit": "hit"},
            {"stat_id": "move_speed", "initial": 7, "minimum": 4, "maximum": 12, "unit": "units/s"},
            {
                "stat_id": "jump_height",
                "initial": 2.4,
                "minimum": 1.8,
                "maximum": 3.5,
                "unit": "units",
            },
            {"stat_id": "enemy_damage", "initial": 1, "minimum": 1, "maximum": 3, "unit": "hit"},
            {
                "stat_id": "checkpoint_spacing",
                "initial": 12,
                "minimum": 8,
                "maximum": 18,
                "unit": "units",
            },
        ],
        "formulas": ["damage = max(1, attack - defense)", "score = collectibles * 100"],
        "difficulty_curve": [
            "zone 1: movement only",
            "zone 2: one hazard family plus enemies",
            "zone 3: combined hazards with shorter recovery windows",
        ],
        "reward_costs": ["checkpoint: complete previous challenge", "goal: reach final platform"],
    }


def _validation_plan(game_spec: GameSpec, level_plan: LevelPlan) -> ValidationPlan:
    scenarios = [
        {
            "scenario_id": "start_to_goal",
            "title": "시작부터 클리어까지 진행",
            "steps": ["spawn player", "traverse zones in order", "touch stage goal"],
            "assertions": ["no blocking overlap", "all zones reachable", "clear state entered"],
        },
        {
            "scenario_id": "checkpoint_recovery",
            "title": "체크포인트 복구",
            "steps": ["activate checkpoint", "touch hazard", "respawn"],
            "assertions": ["respawn at latest checkpoint", "player control restored"],
        },
        {
            "scenario_id": "feature_binding",
            "title": "요청 기능 연결",
            "steps": ["load scene", "bind selected modules", "exercise requested input"],
            "assertions": ["module bound", "player state changes", "feedback is visible"],
        },
    ]
    required_objects = ["Player", "StageGoal"]
    if level_plan["genre"] == "Platformer":
        required_objects += [f"Zone_{zone['zone_id']}" for zone in level_plan["zones"]]
    return {
        "plan_version": "2.0.0",
        "scenarios": scenarios,
        "rules": [
            {
                "rule_id": "level-route-reachable",
                "description": "모든 필수 발판 간격과 높이가 플레이어 이동 한계 이내",
                "required": True,
            },
            {
                "rule_id": "scene-content-bound",
                "description": "설계된 적·함정·보상·체크포인트가 씬에 배치됨",
                "required": True,
            },
            {
                "rule_id": "requested-feature-connected",
                "description": "요청 기능 모듈이 플레이어 또는 UI에 바인딩됨",
                "required": True,
            },
        ],
        "required_scene_objects": required_objects,
        "required_feature_bindings": list(game_spec["mechanics"]),
    }


def _validate_platformer_route(level: LevelPlan) -> None:
    mechanics = {mechanic for zone in level["zones"] for mechanic in zone["required_mechanics"]}
    if not mechanics:
        raise ValueError("Platformer zones must require progression mechanics")
    if not set(level["zones"][-1]["required_mechanics"]).issuperset(mechanics):
        raise ValueError("Mastery zone must combine all introduced mechanics")

    platforms = [platform for zone in level["zones"] for platform in zone["platforms"]]
    if len(platforms) < 10:
        raise ValueError("Platformer route requires at least ten planned platforms")
    ordered_zones = sorted(level["zones"], key=lambda item: item["start_x"])
    if ordered_zones != level["zones"]:
        raise ValueError("Platformer zones must be ordered from left to right")
    for zone in level["zones"]:
        if zone["start_x"] >= zone["end_x"]:
            raise ValueError(f"Zone {zone['zone_id']} has an invalid horizontal range")
        placements = [
            *zone["hazards"],
            *zone["enemies"],
            *zone["collectibles"],
        ]
        if zone["checkpoint"] is not None:
            placements.append(zone["checkpoint"])
        for item in [*zone["platforms"], *placements]:
            if not zone["start_x"] - 1 <= item["x"] <= zone["end_x"] + 1:
                raise ValueError(
                    f"{item.get('placement_id', item.get('platform_id'))} is outside "
                    f"zone {zone['zone_id']}"
                )

    ordered = sorted(platforms, key=lambda item: item["x"])
    for current in ordered:
        if current["width"] < level["minimum_landing_width"]:
            raise ValueError(f"Platform {current['platform_id']} is too narrow")
    for previous, current in pairwise(ordered):
        gap = current["x"] - current["width"] / 2 - (previous["x"] + previous["width"] / 2)
        if gap > level["max_horizontal_gap"]:
            raise ValueError(f"Route gap before {current['platform_id']} is too wide")
        if current["y"] - previous["y"] > level["max_step_up"]:
            raise ValueError(f"Route step before {current['platform_id']} is too high")


def _count_placements(level: LevelPlan, collection: str, archetype: str) -> int:
    return sum(
        1
        for zone in level["zones"]
        for placement in zone[collection]  # type: ignore[literal-required]
        if placement["archetype"] == archetype
    )

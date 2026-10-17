"""Vertical-slice game design contracts and safe deterministic fallbacks.

The v2 documents deliberately separate direction, systems, content, level,
balance, presentation, and validation.  A small local model can improve one
document at a time without being asked to invent a complete Unity game in one
response.  The deterministic platformer plan remains the safety net and is
always traversable under the movement limits recorded in the plan.
"""

from __future__ import annotations

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


def build_design_v2(game_spec: GameSpec, design_intent: str) -> DesignV2Bundle:
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
    content_plan = _content_plan(game_spec)
    level_plan = (
        _platformer_level_plan(game_spec)
        if game_spec["genre"] == "Platformer"
        else _generic_level_plan(game_spec)
    )
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


def _content_plan(game_spec: GameSpec) -> ContentPlan:
    if game_spec["genre"] == "Platformer":
        return {
            "plan_version": "2.0.0",
            "enemies": [
                {
                    "content_id": "patrol_enemy",
                    "role": "이동 타이밍 학습",
                    "count": 2,
                    "stats": [
                        {"stat_id": "health", "value": 1},
                        {"stat_id": "speed", "value": 1.8},
                        {"stat_id": "contact_damage", "value": 1},
                        {"stat_id": "patrol_range", "value": 1.5},
                    ],
                    "behaviors": ["patrol platform", "turn at edge", "damage on contact"],
                },
                {
                    "content_id": "fast_patrol_enemy",
                    "role": "빠른 대응과 대시 사용 유도",
                    "count": 1,
                    "stats": [
                        {"stat_id": "health", "value": 1},
                        {"stat_id": "speed", "value": 3.0},
                        {"stat_id": "contact_damage", "value": 1},
                        {"stat_id": "patrol_range", "value": 2.0},
                    ],
                    "behaviors": ["fast patrol", "turn at edge", "damage on contact"],
                },
                {
                    "content_id": "armored_patrol_enemy",
                    "role": "마지막 구역의 회피 경로 압박",
                    "count": 1,
                    "stats": [
                        {"stat_id": "health", "value": 3},
                        {"stat_id": "speed", "value": 1.1},
                        {"stat_id": "contact_damage", "value": 2},
                        {"stat_id": "patrol_range", "value": 1.2},
                    ],
                    "behaviors": ["slow patrol", "high durability", "damage on contact"],
                },
            ],
            "obstacles": [
                {
                    "content_id": "floor_spike",
                    "role": "점프 정확도 검사",
                    "count": 3,
                    "stats": [
                        {"stat_id": "damage", "value": 1},
                        {"stat_id": "reset_delay", "value": 0.3},
                    ],
                    "behaviors": ["damage on contact", "respawn at checkpoint"],
                },
                {
                    "content_id": "timed_spike",
                    "role": "이동 타이밍과 정지 판단 검사",
                    "count": 2,
                    "stats": [
                        {"stat_id": "damage", "value": 1},
                        {"stat_id": "reset_delay", "value": 0.2},
                    ],
                    "behaviors": ["timed danger", "damage on contact", "checkpoint respawn"],
                },
                {
                    "content_id": "damage_orb",
                    "role": "최종 구역의 공중 경로 제한",
                    "count": 1,
                    "stats": [{"stat_id": "damage", "value": 2}],
                    "behaviors": ["stationary aerial hazard", "checkpoint respawn"],
                },
            ],
            "rewards": [
                {
                    "content_id": "route_collectible",
                    "role": "안전 경로 유도",
                    "count": 6,
                    "stats": [{"stat_id": "score", "value": 1}],
                    "behaviors": ["pickup", "update hud"],
                },
                {
                    "content_id": "bonus_collectible",
                    "role": "위험한 응용 경로에 추가 보상 제공",
                    "count": 3,
                    "stats": [{"stat_id": "score", "value": 3}],
                    "behaviors": ["pickup", "bonus feedback", "update hud"],
                },
            ],
            "stages": ["movement tutorial", "hazard challenge", "mastery run"],
            "final_goal": "필수 수집물을 획득하고 세 번째 구역의 목표 문에 도달",
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


def _platformer_level_plan(game_spec: GameSpec) -> LevelPlan:
    mechanics = list(dict.fromkeys(game_spec["mechanics"]))
    tutorial_mechanics = mechanics[: max(1, len(mechanics) // 3)]
    challenge_mechanics = mechanics[: max(1, (len(mechanics) * 2) // 3)]
    zones: list[LevelZone] = [
        {
            "zone_id": "tutorial",
            "title": "움직임 훈련장",
            "purpose": "tutorial",
            "challenge": "이동·점프·요청 이동 기능을 안전하게 한 번씩 사용",
            "reward": "첫 체크포인트와 수집물 3개",
            "difficulty": 1,
            "required_mechanics": tutorial_mechanics,
            "start_x": -18,
            "end_x": -6,
            "checkpoint": _placement("checkpoint_1", "checkpoint", -6.5, -2.7),
            "platforms": [
                _platform("tutorial_1", -15.5, -2.2, 3.2),
                _platform("tutorial_2", -12.2, -1.3, 3.0),
                _platform("tutorial_3", -9.0, -0.4, 3.0),
                _platform("tutorial_4", -6.2, -1.2, 2.8),
            ],
            "hazards": [_placement("hazard_1", "floor_spike", -10.6, -3.35)],
            "enemies": [],
            "collectibles": [
                _placement("collectible_1", "route_collectible", -15.5, -1.35),
                _placement("collectible_2", "route_collectible", -12.2, -0.45),
                _placement("collectible_3", "bonus_collectible", -9.0, 0.45),
            ],
        },
        {
            "zone_id": "challenge",
            "title": "교차 위험 구간",
            "purpose": "challenge",
            "challenge": "순찰 적과 바닥 함정을 피해 높이가 다른 발판을 연속 통과",
            "reward": "두 번째 체크포인트와 수집물 3개",
            "difficulty": 2,
            "required_mechanics": challenge_mechanics,
            "start_x": -6,
            "end_x": 7,
            "checkpoint": _placement("checkpoint_2", "checkpoint", 6.5, -2.7),
            "platforms": [
                _platform("challenge_1", -3.5, -2.0, 2.8),
                _platform("challenge_2", -0.5, -0.9, 2.8),
                _platform("challenge_3", 2.5, 0.1, 2.8),
                _platform("challenge_4", 5.4, -1.0, 2.8),
            ],
            "hazards": [
                _placement("hazard_2", "floor_spike", -2.0, -3.35),
                _placement("hazard_3", "timed_spike", 4.0, -3.35),
            ],
            "enemies": [
                _placement("enemy_1", "patrol_enemy", -0.5, -0.05),
                _placement("enemy_2", "fast_patrol_enemy", 5.4, -0.15),
            ],
            "collectibles": [
                _placement("collectible_4", "route_collectible", -3.5, -1.15),
                _placement("collectible_5", "route_collectible", 2.5, 0.95),
                _placement("collectible_6", "bonus_collectible", 5.4, -0.15),
            ],
        },
        {
            "zone_id": "mastery",
            "title": "최종 응용 구간",
            "purpose": "mastery",
            "challenge": "적과 연속 함정 사이에서 배운 이동 기능을 조합",
            "reward": "목표 문 개방과 클리어",
            "difficulty": 3,
            "required_mechanics": mechanics,
            "start_x": 7,
            "end_x": 20,
            "checkpoint": None,
            "platforms": [
                _platform("mastery_1", 8.5, -1.9, 2.8),
                _platform("mastery_2", 11.4, -0.8, 2.8),
                _platform("mastery_3", 14.3, 0.25, 2.8),
                _platform("mastery_4", 17.2, -0.7, 3.0),
                _platform("mastery_goal", 19.5, -1.7, 3.2, "goal"),
            ],
            "hazards": [
                _placement("hazard_4", "floor_spike", 10.0, -3.35),
                _placement("hazard_5", "timed_spike", 13.0, -3.35),
                _placement("hazard_6", "damage_orb", 16.0, -2.2),
            ],
            "enemies": [
                _placement("enemy_3", "patrol_enemy", 11.4, 0.05),
                _placement("enemy_4", "armored_patrol_enemy", 17.2, 0.15),
            ],
            "collectibles": [
                _placement("collectible_7", "route_collectible", 8.5, -1.05),
                _placement("collectible_8", "route_collectible", 14.3, 1.1),
                _placement("collectible_9", "bonus_collectible", 17.2, 0.2),
            ],
        },
    ]
    return {
        "plan_version": "2.0.0",
        "genre": "Platformer",
        "player_spawn": _placement("player_spawn", "player", -19, -2.75),
        "goal": _placement("stage_goal", "goal", 20, -0.45),
        "zones": zones,
        "safe_start_seconds": 8.0,
        "camera_orthographic_size": 5.5,
        "max_horizontal_gap": 1.4,
        "max_step_up": 1.15,
        "minimum_landing_width": 2.4,
    }


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
        required_objects += ["Zone_tutorial", "Zone_challenge", "Zone_mastery"]
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

"""Build an executable, genre-aware implementation plan for a non-trivial prototype."""

from __future__ import annotations

from copy import deepcopy

from mainflow.contracts import (
    GameImplementationPlan,
    GameSpec,
    GenreProfile,
    ImplementationSystem,
    PlannedContent,
    PlaytestScenario,
)


def _system(
    system_id: str,
    modules: list[str],
    responsibilities: list[str],
    depends_on: list[str] | None = None,
) -> ImplementationSystem:
    return {
        "system_id": system_id,
        "module_ids": modules,
        "depends_on": depends_on or [],
        "responsibilities": responsibilities,
    }


def _content(archetype: str, count: int, purpose: str) -> PlannedContent:
    return {"archetype": archetype, "count": count, "purpose": purpose}


def _scenario(
    scenario_id: str,
    title: str,
    steps: list[str],
    assertions: list[str],
) -> PlaytestScenario:
    return {
        "scenario_id": scenario_id,
        "title": title,
        "steps": steps,
        "assertions": assertions,
    }


BASE_SYSTEMS = [
    _system(
        "application_flow",
        ["game_bootstrap", "game_state_store", "scene_flow_manager"],
        ["게임 시작·일시정지·재시작 상태를 관리한다.", "승패 이후 결과 흐름을 전환한다."],
    ),
    _system(
        "presentation",
        ["ui_router", "audio_manager", "options_menu", "asset_registry"],
        [
            "HUD·옵션·결과 화면을 표시한다.",
            "ESC 일시정지와 소리 조정을 처리한다.",
            "검증된 이미지와 사운드를 런타임 객체에 연결한다.",
        ],
        ["application_flow"],
    ),
    _system(
        "persistence_and_validation",
        ["save_system", "validation_probe"],
        ["진행 상태를 저장한다.", "핵심 플레이 시나리오의 상태를 관찰 가능하게 만든다."],
        ["application_flow"],
    ),
]


GENRE_PLANS: dict[GenreProfile, GameImplementationPlan] = {
    "Platformer": {
        "plan_version": "1.0.0",
        "complexity_tier": "advanced_prototype",
        "minimum_session_minutes": 8,
        "core_loop_phases": [
            "탐색",
            "이동 도전",
            "위험 회피 또는 전투",
            "수집",
            "체크포인트",
            "스테이지 완료",
        ],
        "systems": BASE_SYSTEMS
        + [
            _system(
                "player_traversal",
                ["input_adapter", "platformer_movement"],
                [
                    "좌우 이동과 반응성 있는 점프를 제공한다.",
                    "추가 이동 능력과 지형 충돌을 결합한다.",
                ],
            ),
            _system(
                "stage_progression",
                ["collectible_system", "goal_system", "health_damage_system"],
                [
                    "수집·위험·낙사·목표 지점을 하나의 스테이지 진행으로 연결한다.",
                    "체크포인트에서 재시작한다.",
                ],
                ["player_traversal", "application_flow"],
            ),
        ],
        "content": [
            _content("platform", 10, "높이와 간격이 달라지는 이동 경로"),
            _content("collectible", 8, "위험한 경로를 탐색할 동기"),
            _content("hazard", 5, "피해와 재시작을 검증하는 장애물"),
            _content("enemy", 3, "이동 패턴을 방해하는 적"),
            _content("checkpoint", 2, "중간 진행 저장 지점"),
            _content("stage_goal", 1, "스테이지 종료 목표"),
        ],
        "ui_screens": ["hud", "pause", "checkpoint_notice", "stage_result"],
        "playtest_scenarios": [
            _scenario(
                "platformer_traversal",
                "이동과 점프",
                ["이동한다.", "연속된 발판 세 개를 점프한다."],
                ["입력마다 이동한다.", "점프 입력이 누락되지 않는다."],
            ),
            _scenario(
                "platformer_failure",
                "피해와 체크포인트",
                ["체크포인트를 통과한다.", "장애물에 닿아 사망한다."],
                ["체력이 감소한다.", "마지막 체크포인트에서 재시작한다."],
            ),
            _scenario(
                "platformer_clear",
                "수집과 완료",
                ["필수 수집물을 모은다.", "목표에 도달한다."],
                ["HUD 수량이 갱신된다.", "결과 화면이 표시된다."],
            ),
        ],
    },
    "TowerDefense": {
        "plan_version": "1.0.0",
        "complexity_tier": "advanced_prototype",
        "minimum_session_minutes": 10,
        "core_loop_phases": [
            "타워 배치",
            "웨이브 시작",
            "자동 전투",
            "보상 획득",
            "강화",
            "다음 웨이브",
        ],
        "systems": BASE_SYSTEMS
        + [
            _system(
                "wave_combat",
                [
                    "wave_spawner",
                    "tower_targeting_system",
                    "projectile_system",
                    "health_damage_system",
                ],
                [
                    "복수 웨이브와 적 체력 증가를 처리한다.",
                    "타워가 사거리와 공격 주기에 따라 적을 공격한다.",
                ],
            ),
            _system(
                "defense_economy",
                ["economy_system", "base_defense_system", "tower_upgrade_system"],
                ["처치 보상으로 배치·강화를 구매한다.", "통과한 적이 기지 생명을 감소시킨다."],
                ["wave_combat"],
            ),
        ],
        "content": [
            _content("path_waypoint", 10, "굽은 적 이동 경로"),
            _content("tower_slot", 8, "전략적 배치 지점"),
            _content("enemy_variant", 4, "속도·체력이 다른 적 유형"),
            _content("wave", 6, "점진적으로 강해지는 전투"),
            _content("base", 1, "방어 목표"),
        ],
        "ui_screens": ["hud", "build_menu", "tower_upgrade", "wave_result", "game_result"],
        "playtest_scenarios": [
            _scenario(
                "tower_build",
                "배치와 비용",
                ["타워 슬롯을 선택한다.", "타워를 구매한다."],
                ["재화가 감소한다.", "타워가 생성된다."],
            ),
            _scenario(
                "tower_wave",
                "웨이브 전투",
                ["웨이브를 시작한다.", "적이 사거리에 진입한다."],
                ["적이 경로를 따른다.", "타워가 공격하고 보상을 지급한다."],
            ),
            _scenario(
                "tower_loss",
                "기지 피해",
                ["적을 종점까지 통과시킨다."],
                ["기지 생명이 감소한다.", "0이면 결과 화면이 표시된다."],
            ),
        ],
    },
    "CardGame": {
        "plan_version": "1.0.0",
        "complexity_tier": "advanced_prototype",
        "minimum_session_minutes": 10,
        "core_loop_phases": [
            "드로우",
            "자원 충전",
            "카드 선택",
            "효과 해결",
            "상대 행동",
            "턴 종료",
        ],
        "systems": BASE_SYSTEMS
        + [
            _system(
                "card_battle",
                [
                    "deck_system",
                    "turn_system",
                    "card_resource_system",
                    "card_effect_system",
                    "health_damage_system",
                ],
                ["덱·손패·버림 더미를 순환시킨다.", "대상 선택과 카드 효과를 순서대로 해결한다."],
            ),
            _system(
                "opponent_logic",
                ["event_rule_engine"],
                ["상대가 현재 상태에 따라 카드를 선택한다.", "승패 조건을 판정한다."],
                ["card_battle"],
            ),
        ],
        "content": [
            _content("card", 20, "공격·방어·강화 카드 풀"),
            _content("starting_hand_slot", 5, "플레이어 손패"),
            _content("enemy_intent", 6, "예고되는 상대 행동"),
            _content("encounter", 3, "난도가 상승하는 전투"),
        ],
        "ui_screens": ["battle_hud", "hand", "target_selector", "card_detail", "result"],
        "playtest_scenarios": [
            _scenario(
                "card_turn",
                "완전한 한 턴",
                ["카드를 뽑는다.", "자원을 사용해 카드를 낸다.", "턴을 종료한다."],
                ["손패와 자원이 갱신된다.", "상대 행동 후 턴이 돌아온다."],
            ),
            _scenario(
                "card_target",
                "대상과 효과",
                ["대상이 필요한 카드를 선택한다.", "적을 선택한다."],
                ["선택한 대상에만 효과가 적용된다."],
            ),
            _scenario(
                "card_result",
                "승패",
                ["상대 또는 플레이어 체력을 0으로 만든다."],
                ["결과 화면과 재시작이 제공된다."],
            ),
        ],
    },
    "VisualNovel": {
        "plan_version": "1.0.0",
        "complexity_tier": "advanced_prototype",
        "minimum_session_minutes": 12,
        "core_loop_phases": [
            "장면 진입",
            "대화 진행",
            "선택",
            "플래그·호감도 변경",
            "분기",
            "엔딩",
        ],
        "systems": BASE_SYSTEMS
        + [
            _system(
                "narrative",
                ["dialogue_runner", "choice_branch_system", "flag_system", "ending_resolver"],
                [
                    "화자·표정·배경을 대사와 동기화한다.",
                    "선택 결과를 플래그와 엔딩 조건에 반영한다.",
                ],
            ),
            _system(
                "narrative_navigation",
                ["save_system", "ui_router"],
                ["대화 기록·자동 진행·건너뛰기·저장/불러오기를 제공한다."],
                ["narrative"],
            ),
        ],
        "content": [
            _content("dialogue_line", 40, "도입·갈등·결말 대화"),
            _content("choice", 6, "분기 선택"),
            _content("character", 3, "표정이 변하는 등장인물"),
            _content("background", 4, "장면 전환"),
            _content("ending", 3, "서로 다른 조건의 결말"),
        ],
        "ui_screens": ["dialogue", "choice", "backlog", "save_load", "ending"],
        "playtest_scenarios": [
            _scenario(
                "novel_branch",
                "선택 분기",
                ["첫 선택에서 A를 고른다.", "후속 장면을 진행한다."],
                ["플래그가 기록된다.", "A 전용 대사가 표시된다."],
            ),
            _scenario(
                "novel_history",
                "기록과 저장",
                ["대화를 진행한다.", "기록과 저장 화면을 연다."],
                ["지난 대사가 보인다.", "저장 후 같은 위치를 복원한다."],
            ),
            _scenario(
                "novel_endings",
                "복수 엔딩",
                ["서로 다른 선택 조합을 진행한다."],
                ["조건에 따라 다른 엔딩에 도달한다."],
            ),
        ],
    },
    "RaisingSimulation": {
        "plan_version": "1.0.0",
        "complexity_tier": "advanced_prototype",
        "minimum_session_minutes": 12,
        "core_loop_phases": [
            "일정 확인",
            "행동 선택",
            "능력치·피로 변화",
            "조건 이벤트",
            "주차 정산",
            "엔딩 판정",
        ],
        "systems": BASE_SYSTEMS
        + [
            _system(
                "raising_loop",
                [
                    "time_turn_system",
                    "stat_system",
                    "activity_system",
                    "schedule_system",
                    "economy_system",
                ],
                [
                    "행동 비용과 시간 경과를 함께 적용한다.",
                    "능력치·피로·재화의 상충 관계를 만든다.",
                ],
            ),
            _system(
                "raising_outcome",
                ["event_rule_engine", "raising_ending_resolver"],
                ["조건 이벤트와 복수 엔딩을 판정한다."],
                ["raising_loop"],
            ),
        ],
        "content": [
            _content("activity", 8, "훈련·공부·일·휴식 선택"),
            _content("stat", 6, "육성 결과를 만드는 능력치"),
            _content("conditional_event", 10, "상태에 반응하는 사건"),
            _content("week", 8, "제한된 육성 기간"),
            _content("ending", 4, "능력치 조합별 결과"),
        ],
        "ui_screens": ["status", "schedule", "activity_result", "event", "weekly_report", "ending"],
        "playtest_scenarios": [
            _scenario(
                "raising_activity",
                "행동 결과",
                ["행동을 선택한다."],
                ["시간·능력치·피로·재화가 규칙대로 변한다."],
            ),
            _scenario(
                "raising_event",
                "조건 이벤트",
                ["필요 능력치를 달성한다.", "날짜를 진행한다."],
                ["조건 이벤트가 한 번 발생한다."],
            ),
            _scenario(
                "raising_ending",
                "기간과 엔딩",
                ["마지막 주까지 진행한다."],
                ["최종 상태에 맞는 엔딩과 요약이 표시된다."],
            ),
        ],
    },
    "SurvivorLike": {
        "plan_version": "1.0.0",
        "complexity_tier": "advanced_prototype",
        "minimum_session_minutes": 10,
        "core_loop_phases": [
            "이동",
            "자동 공격",
            "적 처치",
            "경험치 획득",
            "3개 강화 중 선택",
            "강해진 웨이브 생존",
        ],
        "systems": BASE_SYSTEMS
        + [
            _system(
                "survival_combat",
                [
                    "top_down_movement",
                    "health_damage_system",
                    "enemy_spawn_system",
                    "auto_target_system",
                    "projectile_system",
                ],
                [
                    "플레이어 이동과 자동 조준 공격을 동시에 실행한다.",
                    "시간에 따라 적 수·체력·속도를 증가시킨다.",
                ],
            ),
            _system(
                "wing_progression",
                ["experience_system", "rarity_system", "upgrade_selection_system"],
                [
                    "처치 경험치로 레벨업한다.",
                    "희귀도가 있는 세 선택지로 날개 능력과 외형 단계를 강화한다.",
                ],
                ["survival_combat"],
            ),
        ],
        "content": [
            _content("enemy_variant", 5, "속도·체력·행동이 다른 적"),
            _content("wave_stage", 8, "시간 기반 난도 상승"),
            _content("upgrade", 16, "공격력·공속·이속·깃털 수 조합"),
            _content("arena_marker", 20, "전투 공간 경계"),
            _content("elite_enemy", 3, "주기적 고난도 적"),
        ],
        "ui_screens": ["combat_hud", "upgrade_selection", "pause", "game_result"],
        "playtest_scenarios": [
            _scenario(
                "survivor_combat",
                "자동 전투",
                ["적에게 접근한다.", "공격 없이 이동한다."],
                ["가까운 적을 자동 공격한다.", "처치 시 경험치가 생성된다."],
            ),
            _scenario(
                "survivor_upgrade",
                "날개 강화",
                ["레벨업한다.", "세 선택지 중 하나를 고른다."],
                ["희귀도가 표시된다.", "선택한 능력만 즉시 강화된다."],
            ),
            _scenario(
                "survivor_scaling",
                "난도 상승",
                ["여러 웨이브를 생존한다."],
                ["적 밀도나 능력치가 증가한다.", "사망 시 결과와 재시작이 표시된다."],
            ),
        ],
    },
}


def build_implementation_plan(
    game_spec: GameSpec,
    custom_mechanics: list[str] | None = None,
) -> GameImplementationPlan:
    """Return a deterministic advanced-prototype plan and include custom mechanics."""

    plan = deepcopy(GENRE_PLANS[game_spec["genre"]])
    custom_modules = custom_mechanics or []
    if custom_modules:
        plan["systems"].append(
            _system(
                "requested_custom_features",
                custom_modules,
                [feature["description"] for feature in game_spec["features"]],
                [plan["systems"][-1]["system_id"]],
            )
        )
    return plan

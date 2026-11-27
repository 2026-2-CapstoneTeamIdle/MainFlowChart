from __future__ import annotations

import copy
import unittest

from game_pipeline.design_catalog import normalize_game_spec
from game_pipeline.design_v2 import build_design_v2, validate_design_v2
from game_pipeline.design_v2_planner import StagedDesignV2Planner
from game_pipeline.asset_specs import build_sound_generation_spec
from game_pipeline.gameplay_contracts import (
    build_pacing_contract,
    build_ui_contract,
    compact_platformer_requested,
    checkpoint_respawn_requested,
    requested_collectible_count,
    requested_play_minutes,
    trim_compact_platformer_spec,
    requested_zone_count,
)


class GameplayContractsTest(unittest.TestCase):
    def test_compact_stage_allows_explicit_gem_without_excluded_content(self) -> None:
        condition = (
            "좌우 방향키로 이동하고 Space로 점프하는 간단한 2D 플랫포머를 만든다. "
            "작은 단일 스테이지에 바닥, 발판 3개, 보석 1개, 출구 1개만 배치한다. "
            "보석을 획득한 뒤 출구에 도착하면 승리 화면과 다시 시작 버튼을 표시한다. "
            "화면에는 조작법과 보석 획득 여부를 표시한다. 낙사하면 시작 위치로 돌아온다. "
            "적, 전투, 체력, 체크포인트, 추가 스테이지는 구현하지 않는다."
        )
        spec = trim_compact_platformer_spec(normalize_game_spec("플랫포머"), condition)
        self.assertIn("collectible", spec["mechanics"])
        self.assertNotIn("health_damage", spec["mechanics"])
        design = build_design_v2(spec, condition)
        validate_design_v2(design)
        zone = design["level_plan"]["zones"][0]
        self.assertEqual(len(zone["platforms"]), 3)
        self.assertEqual(len(zone["collectibles"]), 1)
        self.assertFalse(zone["enemies"])
        self.assertFalse(zone["hazards"])
        self.assertIsNone(zone["checkpoint"])
        self.assertIn("collectibles", design["system_design"]["resources"])
        wrong = copy.deepcopy(design)
        wrong["level_plan"]["zones"][0]["collectibles"] = []
        with self.assertRaisesRegex(ValueError, "requires 1 collectibles"):
            validate_design_v2(wrong)

    def test_explicit_playtime_survives_design_and_pacing_contract(self) -> None:
        spec = normalize_game_spec("플랫포머")
        condition = "서로 다른 구역 네 개로 구성된 약 5분 분량의 게임"
        design = build_design_v2(spec, condition)

        validate_design_v2(design)
        contract = build_pacing_contract(spec, design, condition)

        self.assertEqual(requested_play_minutes(condition), 5)
        self.assertEqual(design["game_design"]["target_play_minutes"], 5)
        self.assertEqual(contract["target_play_minutes"], 5)
        self.assertEqual(contract["target_duration_seconds"], 300)
        self.assertEqual(len(design["level_plan"]["zones"]), 4)
        self.assertGreaterEqual(
            sum(len(zone["platforms"]) for zone in design["level_plan"]["zones"]), 30
        )
        self.assertEqual(requested_zone_count("최소 4개의 구역", default=3), 4)

    def test_short_single_stage_does_not_inherit_five_minute_contract(self) -> None:
        spec = normalize_game_spec("플랫포머")
        condition = (
            "2D 사이드뷰 플랫포머. 하나의 짧은 스테이지를 만든다. "
            "고정 발판 6개와 작은 틈 2개를 배치한다. "
            "적, 공격, 체크포인트, 수집품은 필요 없다."
        )
        design = build_design_v2(spec, condition)
        validate_design_v2(design)
        contract = build_pacing_contract(spec, design, condition)
        zone = design["level_plan"]["zones"][0]

        self.assertTrue(compact_platformer_requested(condition))
        self.assertEqual(design["game_design"]["target_play_minutes"], 0)
        self.assertEqual(contract["minimum_normal_play_seconds"], 0)
        self.assertEqual(contract["target_duration_seconds"], 0)
        self.assertEqual(len(design["level_plan"]["zones"]), 1)
        self.assertEqual(len(zone["platforms"]), 6)
        self.assertFalse(zone["enemies"])
        self.assertFalse(zone["hazards"])
        self.assertFalse(zone["collectibles"])
        self.assertIsNone(zone["checkpoint"])
        self.assertEqual(
            {item["scenario_id"] for item in design["validation_plan"]["scenarios"]},
            {"feature_binding", "checkpoint_recovery", "start_to_goal"},
        )
        self.assertEqual(
            {item["screen_id"] for item in design["presentation_plan"]["screen_requirements"]},
            {"hud", "stage_result"},
        )

    def test_single_stage_six_platforms_without_short_word_is_compact(self) -> None:
        spec = normalize_game_spec("플랫포머")
        condition = (
            "생성된 이미지와 사운드가 적용된 2D 플랫포머를 만든다. "
            "스테이지는 하나이며 시작 지점에서 출구까지 이동하면 클리어된다. "
            "고정 발판 6개와 작은 틈 2개를 배치한다. "
            "적, 공격, 체력, 체크포인트, 수집품은 필요 없다."
        )
        design = build_design_v2(spec, condition)
        validate_design_v2(design)
        self.assertTrue(compact_platformer_requested(condition))
        self.assertEqual(
            build_pacing_contract(spec, design, condition)["minimum_normal_play_seconds"], 0
        )
        self.assertEqual(len(design["level_plan"]["zones"]), 1)

    def test_compact_spec_removes_contradicting_preset_mechanics(self) -> None:
        condition = "스테이지는 하나이며 고정 발판 6개를 둔다. 적, 체력, 수집품은 필요 없다."
        spec = trim_compact_platformer_spec(normalize_game_spec("플랫포머"), condition)
        self.assertEqual(spec["mechanics"], ["platformer_movement", "goal"])
        self.assertEqual(spec["lose_conditions"], [])
        design = build_design_v2(spec, condition)
        validate_design_v2(design)
        self.assertEqual(
            [stat["stat_id"] for stat in design["balance_plan"]["stats"]],
            ["move_speed", "jump_height"],
        )
        self.assertEqual(design["game_design"]["lose_conditions"], [])

    def test_explicit_duration_overrides_compact_words(self) -> None:
        condition = "하나의 짧은 스테이지지만 약 5분 분량으로 만든다"
        self.assertFalse(compact_platformer_requested(condition))
        self.assertEqual(requested_play_minutes(condition), 5)

    def test_planner_cannot_shorten_requested_duration(self) -> None:
        spec = normalize_game_spec("플랫포머")
        baseline = build_design_v2(spec, "약 5분 분량")
        shortened = copy.deepcopy(baseline["game_design"])
        shortened["target_play_minutes"] = 3

        with self.assertRaisesRegex(ValueError, "preserve the requested playtime"):
            StagedDesignV2Planner._validate_stage_response(
                "game_design", shortened, baseline["game_design"], baseline, baseline
            )

    def test_collectible_outside_connected_platform_route_is_rejected(self) -> None:
        spec = normalize_game_spec("플랫포머")
        design = build_design_v2(spec, "파편을 모아 출구에 도달하는 5분 게임")
        last_zone = design["level_plan"]["zones"][-1]
        last_platform = last_zone["platforms"][-1]
        unreachable_x = last_platform["x"] + last_platform["width"] / 2 + 4
        last_zone["collectibles"][-1]["x"] = unreachable_x
        last_zone["end_x"] = unreachable_x + 1

        with self.assertRaisesRegex(ValueError, "is unreachable"):
            validate_design_v2(design)

    def test_ui_contract_tracks_regions_and_state_screens(self) -> None:
        spec = normalize_game_spec("플랫포머")
        design = build_design_v2(spec, "체력과 목표가 보이는 5분 게임")

        contract = build_ui_contract(spec, design)

        self.assertEqual(contract["reference_resolution"], [1280, 720])
        self.assertEqual(
            {item["screen_id"] for item in contract["state_screens"]},
            {item["screen_id"] for item in design["presentation_plan"]["screen_requirements"]},
        )
        self.assertTrue(all(item["visible_data"] for item in contract["hud_regions"]))

    def test_survivor_kill_count_is_required_in_live_hud(self) -> None:
        spec = normalize_game_spec("뱀서류")
        design = build_design_v2(spec, "적을 처치하고 처치 수를 화면에 표시한다.")
        contract = build_ui_contract(spec, design)

        hud = next(screen for screen in contract["state_screens"] if screen["screen_id"] == "hud")
        self.assertIn("kill count", hud["required_elements"])
        self.assertTrue(
            any("kill count" in region["visible_data"] for region in contract["hud_regions"])
        )

        without_kills = copy.deepcopy(design["presentation_plan"])
        for screen in without_kills["screen_requirements"]:
            if screen["screen_id"] == "hud":
                screen["required_elements"].remove("kill count")
        with self.assertRaisesRegex(ValueError, "required live HUD elements: kill count"):
            StagedDesignV2Planner._validate_stage_response(
                "presentation_plan",
                without_kills,
                design["presentation_plan"],
                design,
                design,
            )

    def test_exact_shard_count_is_preserved_in_level_and_content_plans(self) -> None:
        spec = normalize_game_spec("플랫포머")
        condition = "시간의 파편을 12개 배치한다. 파편 12개 모두 획득 가능해야 한다."
        design = build_design_v2(spec, condition)

        validate_design_v2(design)
        self.assertEqual(requested_collectible_count(condition), 12)
        self.assertEqual(
            sum(len(zone["collectibles"]) for zone in design["level_plan"]["zones"]), 12
        )
        self.assertEqual(sum(item["count"] for item in design["content_plan"]["rewards"]), 12)

        altered = copy.deepcopy(design["level_plan"])
        altered["zones"][-1]["collectibles"].append(
            copy.deepcopy(altered["zones"][-1]["collectibles"][0])
        )
        with self.assertRaisesRegex(ValueError, "requires 12 collectibles"):
            StagedDesignV2Planner._validate_stage_response(
                "level_plan", altered, design["level_plan"], design, design
            )

    def test_checkpoint_respawn_does_not_require_a_defeat_screen(self) -> None:
        spec = normalize_game_spec("플랫포머")
        condition = "체력이 0이 되면 마지막 체크포인트에서 부활한다."
        design = build_design_v2(spec, condition)

        validate_design_v2(design)
        self.assertTrue(checkpoint_respawn_requested(condition))
        self.assertEqual(design["game_design"]["lose_conditions"], [])
        self.assertNotIn("failure", design["presentation_plan"]["ui_screens"])
        self.assertNotIn(
            "failure", {s["screen_id"] for s in build_ui_contract(spec, design)["state_screens"]}
        )

    def test_feedback_sounds_bind_to_runtime_cues(self) -> None:
        self.assertEqual(
            build_sound_generation_spec("player_hit feedback", "player damaged")["audio_cue"],
            "player_hit",
        )
        self.assertEqual(
            build_sound_generation_spec("collectible_pickup feedback", "collectible acquired")[
                "audio_cue"
            ],
            "pickup",
        )

    def test_genre_without_preset_zones_still_gets_a_pacing_segment(self) -> None:
        spec = normalize_game_spec("카드")
        design = build_design_v2(spec, "5분 동안 카드 덱을 구성한다")

        contract = build_pacing_contract(spec, design, "5분 동안 카드 덱을 구성한다")

        self.assertEqual(contract["target_duration_seconds"], 300)
        self.assertEqual(len(contract["segments"]), 1)
        self.assertIsNone(contract["segments"][0]["source_zone_id"])


if __name__ == "__main__":
    unittest.main()

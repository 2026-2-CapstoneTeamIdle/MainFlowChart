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
    checkpoint_respawn_requested,
    requested_collectible_count,
    requested_play_minutes,
    requested_zone_count,
)


class GameplayContractsTest(unittest.TestCase):
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

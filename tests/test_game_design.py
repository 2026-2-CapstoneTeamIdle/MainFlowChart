from __future__ import annotations

import unittest

from game_pipeline import build_game_logic_design, normalize_game_spec


class GameDesignTest(unittest.TestCase):
    def test_each_supported_genre_has_modules_features_and_assets(self) -> None:
        expected_mechanics = {
            "Platformer": "platformer_movement",
            "TowerDefense": "wave_spawn",
            "CardGame": "deck",
            "SurvivorLike": "upgrade_selection",
            "VisualNovel": "dialogue",
            "RaisingSimulation": "activity",
        }

        for genre, mechanic in expected_mechanics.items():
            with self.subTest(genre=genre):
                spec = normalize_game_spec(genre)  # type: ignore[arg-type]
                design = build_game_logic_design(spec)
                self.assertIn(mechanic, spec["mechanics"])
                self.assertTrue(spec["features"])
                self.assertTrue(spec["asset_requirements"])
                self.assertIn("game_bootstrap", design["selected_modules"])
                self.assertFalse(design["unsupported_mechanics"])
                plan = design["implementation_plan"]
                self.assertEqual(plan["complexity_tier"], "advanced_prototype")
                self.assertGreaterEqual(len(plan["systems"]), 5)
                self.assertGreaterEqual(len(plan["content"]), 4)
                self.assertGreaterEqual(len(plan["ui_screens"]), 4)
                self.assertGreaterEqual(len(plan["playtest_scenarios"]), 3)

    def test_platformer_plan_requests_a_multi_system_playable_stage(self) -> None:
        design = build_game_logic_design(normalize_game_spec("플랫포머"))
        plan = design["implementation_plan"]
        counts = {item["archetype"]: item["count"] for item in plan["content"]}

        self.assertGreaterEqual(counts["platform"], 10)
        self.assertGreaterEqual(counts["collectible"], 8)
        self.assertGreaterEqual(counts["hazard"], 5)
        self.assertGreaterEqual(counts["checkpoint"], 2)
        self.assertIn("stage_result", plan["ui_screens"])

        design_v2 = design["design_v2"]
        self.assertEqual(
            set(design_v2),
            {
                "game_design",
                "system_design",
                "content_plan",
                "level_plan",
                "balance_plan",
                "presentation_plan",
                "validation_plan",
            },
        )
        level = design_v2["level_plan"]
        self.assertEqual(
            [zone["purpose"] for zone in level["zones"]],
            ["tutorial", "challenge", "mastery"],
        )
        self.assertGreaterEqual(
            sum(len(zone["platforms"]) for zone in level["zones"]),
            10,
        )
        self.assertGreaterEqual(
            len(design_v2["validation_plan"]["scenarios"]),
            3,
        )
        content = design_v2["content_plan"]
        self.assertGreaterEqual(len(content["enemies"]), 3)
        self.assertGreaterEqual(len(content["obstacles"]), 3)
        self.assertGreaterEqual(len(content["rewards"]), 2)
        balance_ids = {stat["stat_id"] for stat in design_v2["balance_plan"]["stats"]}
        self.assertTrue({"player_health", "move_speed", "jump_height"}.issubset(balance_ids))

    def test_blueprint_is_deterministic_but_changes_with_user_intent(self) -> None:
        spec = normalize_game_spec("플랫포머")
        first = build_game_logic_design(
            spec,
            design_intent="달빛 아래 고성에서 벽을 타고 보물을 찾는다.",
        )
        repeated = build_game_logic_design(
            spec,
            design_intent="달빛 아래 고성에서 벽을 타고 보물을 찾는다.",
        )
        second = build_game_logic_design(
            spec,
            design_intent="용암 동굴을 공중 대시로 탈출한다.",
        )

        self.assertEqual(first["game_blueprint"], repeated["game_blueprint"])
        self.assertNotEqual(
            first["game_blueprint"]["blueprint_id"],
            second["game_blueprint"]["blueprint_id"],
        )
        self.assertGreaterEqual(len(first["game_blueprint"]["entities"]), 5)
        self.assertGreaterEqual(len(first["game_blueprint"]["content"]), 4)

    def test_legacy_action_maps_to_survivor_profile(self) -> None:
        spec = normalize_game_spec("Action")
        self.assertEqual(spec["genre"], "SurvivorLike")
        self.assertIn("projectile", spec["mechanics"])

    def test_korean_input_genres_map_to_the_six_supported_profiles(self) -> None:
        expected_profiles = {
            "플랫포머": "Platformer",
            "타워 디펜스": "TowerDefense",
            "카드": "CardGame",
            "비주얼 노벨": "VisualNovel",
            "육성 시뮬레이션": "RaisingSimulation",
            "뱀서류": "SurvivorLike",
        }

        for genre, profile in expected_profiles.items():
            with self.subTest(genre=genre):
                self.assertEqual(normalize_game_spec(genre)["genre"], profile)  # type: ignore[arg-type]

    def test_every_supported_genre_resolves_only_implemented_mechanics(self) -> None:
        for genre in [
            "플랫포머",
            "타워 디펜스",
            "카드",
            "비주얼 노벨",
            "육성 시뮬레이션",
            "뱀서류",
        ]:
            with self.subTest(genre=genre):
                design = build_game_logic_design(normalize_game_spec(genre))  # type: ignore[arg-type]
                self.assertFalse(design["unsupported_mechanics"])
                self.assertTrue(design["genre_modules"])

    def test_overrides_are_normalized_and_unknown_mechanics_are_reported(self) -> None:
        spec = normalize_game_spec(
            "SurvivorLike",
            {
                "title": "Wing Survivor",
                "features": ["날개가 레벨업 선택에 따라 강화된다."],
                "mechanics": ["top_down_movement", "wing_evolution"],
                "asset_requirements": [
                    {
                        "asset_id": "wing_sprite",
                        "asset_type": "image",
                        "purpose": "플레이어 날개",
                        "description": "단계별 날개 스프라이트",
                        "required": True,
                    }
                ],
            },
        )
        design = build_game_logic_design(spec)
        self.assertEqual(spec["title"], "Wing Survivor")
        self.assertIn(
            "custom_feature_1",
            [feature["feature_id"] for feature in spec["features"]],
        )
        self.assertEqual(design["unsupported_mechanics"], ["wing_evolution"])
        custom_system = design["implementation_plan"]["systems"][-1]
        self.assertEqual(custom_system["system_id"], "requested_custom_features")
        self.assertEqual(custom_system["module_ids"], ["wing_evolution"])

    def test_duplicate_asset_ids_are_rejected(self) -> None:
        duplicate = {
            "asset_id": "same_asset",
            "asset_type": "image",
            "purpose": "test",
            "description": "test asset",
            "required": True,
        }
        with self.assertRaisesRegex(ValueError, "asset_id values must be unique"):
            normalize_game_spec(
                "VisualNovel",
                {"asset_requirements": [duplicate, duplicate]},
            )


if __name__ == "__main__":
    unittest.main()

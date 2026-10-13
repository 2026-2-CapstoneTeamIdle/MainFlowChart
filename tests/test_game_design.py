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

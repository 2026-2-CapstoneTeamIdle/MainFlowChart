from __future__ import annotations

import unittest

from PIL import Image

from game_pipeline import build_game_logic_design, normalize_game_spec
from game_pipeline.scene_visual_assets import scene_visual_requirements
from game_pipeline.unity_asset_applicator import UnityAssetApplicator
from mainflow.image_generation import KIND_PROMPTS

SKY = (20, 22, 56, 255)
ROCK = (120, 120, 130, 255)
GRASS = (90, 200, 120, 255)
DIRT = (40, 20, 60, 255)


def _surface_tile_with_rocks() -> Image.Image:
    """Sky on top, rocks sticking up from the grass, then solid ground from row 12."""

    tile = Image.new("RGBA", (32, 32), SKY)
    tile.paste(ROCK, (4, 5, 10, 12))
    tile.paste(ROCK, (20, 7, 27, 12))
    tile.paste(GRASS, (0, 12, 32, 16))
    tile.paste(DIRT, (0, 16, 32, 32))
    return tile


class SingleSubjectTest(unittest.TestCase):
    def test_object_descriptions_ask_for_one_subject_without_listing_kinds(self) -> None:
        spec = normalize_game_spec("플랫포머", {})
        design = build_game_logic_design(spec, design_intent="점프", variation_seed="seed")

        additions = scene_visual_requirements(spec, design["design_v2"]["level_plan"])

        for item in additions:
            with self.subTest(asset_id=item["asset_id"]):
                self.assertNotIn("종류", item["description"])
                self.assertNotIn("_enemy", item["description"])
                self.assertNotIn("_spike", item["description"])
        enemy = next(item for item in additions if item["asset_id"] == "platformer_enemy")
        self.assertIn("한 마리", enemy["description"])

    def test_sprite_prompt_forbids_groups_and_lineups(self) -> None:
        self.assertIn("exactly one subject", KIND_PROMPTS["sprite"])
        self.assertIn("lineup", KIND_PROMPTS["sprite"])


class FlatSurfaceTest(unittest.TestCase):
    def test_tileset_prompt_asks_for_a_clean_top_edge(self) -> None:
        self.assertIn("flat, clean top edge", KIND_PROMPTS["tileset"])

    def test_rocks_above_the_ground_edge_are_removed(self) -> None:
        cleared = UnityAssetApplicator._clear_surface_sky(_surface_tile_with_rocks())
        alpha = cleared.getchannel("A")

        # Sky and both rocks above row 12 are gone; the ground edge and below stay.
        self.assertTrue(all(alpha.getpixel((x, y)) == 0 for x in range(32) for y in range(12)))
        self.assertEqual(cleared.getpixel((0, 12)), GRASS)
        self.assertEqual(cleared.getpixel((31, 31)), DIRT)

    def test_tile_without_a_clear_ground_edge_is_left_alone(self) -> None:
        tile = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
        tile.paste(GRASS, (0, 25, 32, 32))

        self.assertIs(UnityAssetApplicator._trim_above_surface(tile), tile)


if __name__ == "__main__":
    unittest.main()

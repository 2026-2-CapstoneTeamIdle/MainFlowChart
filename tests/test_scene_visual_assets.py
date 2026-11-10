from __future__ import annotations

import re
import unittest
from copy import deepcopy
from pathlib import Path

from game_pipeline import build_game_logic_design, normalize_game_spec
from game_pipeline.asset_specs import build_image_generation_spec
from game_pipeline.scene_visual_assets import (
    STAGE_BACKGROUND_ASSET_ID,
    scene_visual_requirements,
    with_scene_visual_assets,
)
from mainflow.image_generation import ImageAssetPlan, is_animated_character

BINDER_PATH = (
    Path(__file__).resolve().parent.parent
    / "unity_template/Assets/GameTemplate/Editor/GeneratedAssetBinder.cs"
)


def _design(genre: str):
    spec = normalize_game_spec(genre, {})
    return spec, build_game_logic_design(spec, design_intent="점프와 공격", variation_seed="seed")


def _plan(requirement) -> ImageAssetPlan:
    return ImageAssetPlan(
        asset_id=requirement["asset_id"],
        purpose=requirement["purpose"],
        description=requirement["description"],
        required=requirement["required"],
        filename=f"{requirement['asset_id']}.png",
        unity_binding_key=f"asset_registry:{requirement['asset_id']}",
        kind=build_image_generation_spec(requirement["purpose"], requirement["description"])[
            "kind"
        ],
        generation_spec=build_image_generation_spec(
            requirement["purpose"], requirement["description"]
        ),
    )


class SceneVisualAssetsTest(unittest.TestCase):
    def test_platformer_requests_an_image_for_every_placed_object_category(self) -> None:
        spec, design = _design("플랫포머")

        additions = scene_visual_requirements(spec, design["design_v2"]["level_plan"])

        self.assertEqual(
            [item["asset_id"] for item in additions],
            [
                "platformer_enemy",
                "platformer_hazard",
                "platformer_collectible",
                "platformer_checkpoint",
                "platformer_goal",
                STAGE_BACKGROUND_ASSET_ID,
            ],
        )
        self.assertTrue(all(item["asset_type"] == "image" for item in additions))
        self.assertTrue(all(item["required"] is False for item in additions))
        enemy = additions[0]
        self.assertIn("patrol_enemy", enemy["description"])

    def test_object_images_get_the_intended_kind_and_only_enemies_animate(self) -> None:
        spec, design = _design("플랫포머")
        additions = {
            item["asset_id"]: _plan(item)
            for item in scene_visual_requirements(spec, design["design_v2"]["level_plan"])
        }

        self.assertEqual(additions[STAGE_BACKGROUND_ASSET_ID].kind, "background")
        for asset_id in (
            "platformer_enemy",
            "platformer_hazard",
            "platformer_collectible",
            "platformer_checkpoint",
            "platformer_goal",
        ):
            self.assertEqual(additions[asset_id].kind, "sprite", asset_id)
        animated = sorted(
            asset_id
            for asset_id, plan in additions.items()
            if is_animated_character(plan, "Platformer")
        )
        self.assertEqual(animated, ["platformer_enemy"])

    def test_categories_absent_from_the_level_plan_are_not_requested(self) -> None:
        spec, design = _design("플랫포머")
        level_plan = deepcopy(design["design_v2"]["level_plan"])
        for zone in level_plan["zones"]:
            zone["enemies"] = []
            zone["checkpoint"] = None

        ids = [item["asset_id"] for item in scene_visual_requirements(spec, level_plan)]

        self.assertNotIn("platformer_enemy", ids)
        self.assertNotIn("platformer_checkpoint", ids)
        self.assertIn("platformer_hazard", ids)

    def test_existing_background_image_is_not_duplicated(self) -> None:
        spec, design = _design("비주얼 노벨")

        ids = [
            item["asset_id"]
            for item in scene_visual_requirements(spec, design["design_v2"]["level_plan"])
        ]

        self.assertNotIn(STAGE_BACKGROUND_ASSET_ID, ids)

    def test_merge_is_idempotent_and_keeps_preset_assets_first(self) -> None:
        spec, design = _design("플랫포머")
        level_plan = design["design_v2"]["level_plan"]

        merged = with_scene_visual_assets(spec, level_plan)
        again = with_scene_visual_assets(merged, level_plan)

        self.assertIs(again, merged)
        self.assertEqual(
            [item["asset_id"] for item in merged["asset_requirements"]][:4],
            [item["asset_id"] for item in spec["asset_requirements"]],
        )

    def test_rebuilt_design_keeps_the_same_level_plan(self) -> None:
        spec, design = _design("플랫포머")
        merged = with_scene_visual_assets(spec, design["design_v2"]["level_plan"])

        rebuilt = build_game_logic_design(
            merged, design_intent="점프와 공격", variation_seed="seed"
        )

        self.assertEqual(rebuilt["design_v2"]["level_plan"], design["design_v2"]["level_plan"])

    def test_unity_binder_maps_every_requested_object_image(self) -> None:
        binder = BINDER_PATH.read_text(encoding="utf-8")
        spec, design = _design("플랫포머")

        for item in scene_visual_requirements(spec, design["design_v2"]["level_plan"]):
            self.assertRegex(
                binder,
                rf'"{re.escape(item["asset_id"])}" =>',
                f"GeneratedAssetBinder.SceneObjectNames is missing {item['asset_id']}",
            )
        self.assertIn("AssignSprite(renderer, sprite, entry.kind)", binder)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import io
import re
import unittest
from pathlib import Path

from PIL import Image

from game_pipeline.asset_specs import (
    GROUNDED_OBJECT_IDS,
    OBJECT_ART_WIDTH_ROOM,
    OBJECT_FOOTPRINT_UNITS,
    build_image_generation_spec,
)
from mainflow.image_backends import postprocess
from mainflow.image_generation import ImageAssetPlan, ImageRequest

TEMPLATE_ROOT = Path(__file__).resolve().parent.parent / "unity_template/Assets/GameTemplate"
BINDER = TEMPLATE_ROOT / "Editor/GeneratedAssetBinder.cs"
MOVEMENT = TEMPLATE_ROOT / "Runtime/Platformer/PlatformerModules.cs"
ACTORS = TEMPLATE_ROOT / "Runtime/Prototype/PlatformerPrototypeActors.cs"


def _request(asset_id: str) -> ImageRequest:
    spec = build_image_generation_spec("오브젝트", "테스트 오브젝트", asset_id)
    plan = ImageAssetPlan(
        asset_id=asset_id,
        purpose="오브젝트",
        description="테스트 오브젝트",
        required=False,
        filename=f"{asset_id}.png",
        unity_binding_key=f"asset_registry:{asset_id}",
        kind=spec["kind"],
        generation_spec=spec,
    )
    return ImageRequest(
        plan=plan,
        style="Pixel Art",
        mood_style="Fantasy",
        viewpoint="사이드뷰",
        genre="Platformer",
        width=spec["width"],
        height=spec["height"],
        prompt="test",
    )


def _wide_door() -> bytes:
    """A door wider than the goal footprint, like the generated goal art."""

    image = Image.new("RGBA", (1024, 1536), (0, 0, 0, 0))
    image.paste((230, 200, 120, 255), (300, 300, 724, 1050))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _visible_box(png: bytes) -> tuple[Image.Image, tuple[int, int, int, int]]:
    image = Image.open(io.BytesIO(png))
    visible = image.getchannel("A").point(lambda value: 255 if value >= 128 else 0)
    return image, visible.getbbox()


class GroundedSpriteTest(unittest.TestCase):
    def test_grounded_art_touches_the_bottom_edge(self) -> None:
        for asset_id in sorted(GROUNDED_OBJECT_IDS):
            with self.subTest(asset_id=asset_id):
                image, (_, _, _, bottom) = _visible_box(
                    postprocess(_wide_door(), _request(asset_id))
                )
                self.assertEqual(bottom, image.height)

    def test_floating_pickups_stay_centered(self) -> None:
        image, (_, top, _, bottom) = _visible_box(
            postprocess(_wide_door(), _request("platformer_collectible"))
        )

        self.assertLess(bottom, image.height)
        self.assertLessEqual(abs(top - (image.height - bottom)), 1)

    def test_width_room_lets_the_goal_fill_most_of_its_height(self) -> None:
        image, (_, top, _, bottom) = _visible_box(
            postprocess(_wide_door(), _request("platformer_goal"))
        )

        self.assertGreaterEqual((bottom - top) / image.height, 0.8)

    def test_hazards_keep_the_exact_damage_width(self) -> None:
        self.assertNotIn("platformer_hazard", OBJECT_ART_WIDTH_ROOM)
        self.assertTrue(set(OBJECT_ART_WIDTH_ROOM) <= set(OBJECT_FOOTPRINT_UNITS))

    def test_unity_grounded_list_matches_python(self) -> None:
        binder = BINDER.read_text(encoding="utf-8")
        block = re.search(
            r"GroundedAssetIds = new\(StringComparer\.Ordinal\)\s*\{(.*?)\};", binder, re.DOTALL
        )

        self.assertIsNotNone(block)
        self.assertEqual(set(re.findall(r'"(\w+)"', block.group(1))), set(GROUNDED_OBJECT_IDS))
        self.assertIn("GroundedAssetIds.Contains(entry.asset_id) ? box.y / natural.y", binder)

    def test_player_and_patrol_enemy_face_their_movement(self) -> None:
        movement = MOVEMENT.read_text(encoding="utf-8")
        actors = ACTORS.read_text(encoding="utf-8")

        self.assertIn("FaceMovement(movementX);", movement)
        self.assertIn("targetRenderer.flipX = movementX < 0f;", movement)
        self.assertIn("spriteRenderer.flipX = step < 0f;", actors)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import io
import re
import unittest
from pathlib import Path

from PIL import Image

from game_pipeline import UnityProjectGenerator, build_game_logic_design, normalize_game_spec
from game_pipeline.asset_specs import (
    OBJECT_FOOTPRINT_UNITS,
    OBJECT_PIXELS_PER_UNIT,
    build_image_generation_spec,
)
from game_pipeline.scene_visual_assets import with_scene_visual_assets
from mainflow.image_backends import _openai_size, postprocess
from mainflow.image_generation import ImageAssetPlan, ImageRequest

TEMPLATE_ROOT = Path(__file__).resolve().parent.parent / "unity_template"
ASSEMBLER = TEMPLATE_ROOT / "Assets/GameTemplate/Editor/PrefabSceneAssembler.cs"
BINDER = TEMPLATE_ROOT / "Assets/GameTemplate/Editor/GeneratedAssetBinder.cs"
SCROLLER = TEMPLATE_ROOT / "Assets/GameTemplate/Runtime/Prototype/PrototypeBackgroundScroller.cs"


def _request(asset_id: str, purpose: str, description: str) -> ImageRequest:
    spec = build_image_generation_spec(purpose, description, asset_id)
    plan = ImageAssetPlan(
        asset_id=asset_id,
        purpose=purpose,
        description=description,
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


class ObjectFootprintSpecTest(unittest.TestCase):
    def test_object_sprites_follow_the_scene_object_aspect_ratio(self) -> None:
        for asset_id, (width_units, height_units) in OBJECT_FOOTPRINT_UNITS.items():
            with self.subTest(asset_id=asset_id):
                spec = build_image_generation_spec("오브젝트", "테스트 스프라이트", asset_id)
                self.assertEqual(spec["kind"], "sprite")
                self.assertEqual(spec["pixels_per_unit"], OBJECT_PIXELS_PER_UNIT)
                self.assertAlmostEqual(
                    spec["width"] / spec["height"],
                    width_units / height_units,
                    delta=0.15 * width_units / height_units,
                )

    def test_unknown_assets_and_non_sprite_kinds_keep_default_sizes(self) -> None:
        sprite = build_image_generation_spec("적", "적 스프라이트", "enemy_sprite")
        tileset = build_image_generation_spec("맵", "발판과 지형 타일셋", "platformer_tileset")

        self.assertEqual((sprite["width"], sprite["height"]), (64, 64))
        self.assertEqual(sprite["pixels_per_unit"], 32)
        self.assertEqual((tileset["width"], tileset["height"]), (128, 128))
        self.assertEqual(tileset["tile_width"], 32)

    def test_asset_request_carries_footprint_sizes(self) -> None:
        spec = normalize_game_spec("플랫포머", {})
        design = build_game_logic_design(spec, design_intent="점프", variation_seed="seed")
        spec = with_scene_visual_assets(spec, design["design_v2"]["level_plan"])
        design = build_game_logic_design(spec, design_intent="점프", variation_seed="seed")

        request = UnityProjectGenerator().build_asset_request(
            design,
            "image",
            image_style="Pixel Art",
            mood_style="Fantasy",
            viewpoint="사이드뷰",
            reference_image=None,
        )
        sizes = {
            item["asset_id"]: (
                item["generation_spec"]["width"],
                item["generation_spec"]["height"],
            )
            for item in request["assets"]
        }

        self.assertGreater(sizes["platformer_hazard"][0], sizes["platformer_hazard"][1])
        self.assertLess(sizes["platformer_checkpoint"][0], sizes["platformer_checkpoint"][1])
        self.assertLess(sizes["platformer_goal"][0], sizes["platformer_goal"][1])
        self.assertLess(sizes["platformer_player"][0], sizes["platformer_player"][1])


class OrientationTest(unittest.TestCase):
    def test_openai_canvas_matches_sprite_orientation(self) -> None:
        self.assertEqual(
            _openai_size(_request("platformer_checkpoint", "체크포인트", "깃발 기둥")),
            "1024x1536",
        )
        self.assertEqual(
            _openai_size(_request("platformer_hazard", "함정", "가시 함정")), "1536x1024"
        )
        self.assertEqual(_openai_size(_request("platformer_enemy", "적", "적 캐릭터")), "1024x1024")

    def test_tall_art_fills_the_tall_sprite_canvas(self) -> None:
        request = _request("platformer_goal", "골", "출구 문")
        source = Image.new("RGBA", (1024, 1536), (0, 0, 0, 0))
        source.paste((200, 80, 40, 255), (400, 100, 624, 1436))
        buffer = io.BytesIO()
        source.save(buffer, format="PNG")

        result = Image.open(io.BytesIO(postprocess(buffer.getvalue(), request)))
        _, top, _, bottom = result.getchannel("A").getbbox()

        self.assertEqual(result.size, (request.width, request.height))
        self.assertGreaterEqual((bottom - top) / request.height, 0.8)


class UnityPlacementTest(unittest.TestCase):
    def test_platformer_footprints_match_scene_assembler(self) -> None:
        assembler = ASSEMBLER.read_text(encoding="utf-8")

        def has_size(width: float, height: float) -> bool:
            if width == height:
                pattern = rf"Vector2\.one \* {width:g}f|new Vector2\({width:g}f, {height:g}f\)"
            else:
                pattern = rf"new Vector2\({width:g}f, {height:g}f\)"
            return re.search(pattern, assembler) is not None

        self.assertIn("PlatformerPlayerWidth = 0.8f", assembler)
        self.assertIn("PlatformerPlayerHeight = 1.2f", assembler)
        for asset_id, (width, height) in OBJECT_FOOTPRINT_UNITS.items():
            if asset_id == "platformer_player":
                continue
            with self.subTest(asset_id=asset_id):
                self.assertTrue(has_size(width, height), f"{asset_id} {width}x{height}")

    def test_ground_tiles_and_background_scroll_instead_of_stretching(self) -> None:
        binder = BINDER.read_text(encoding="utf-8")

        self.assertIn("AssignTiledSurface(renderer, sprite)", binder)
        self.assertIn("SpriteDrawMode.Tiled", binder)
        self.assertIn("AddComponent<PrototypeBackgroundScroller>", binder)
        self.assertIn('$"{entry.asset_id}_0"', binder)

    def test_background_scroller_is_a_dedicated_runtime_script(self) -> None:
        source = SCROLLER.read_text(encoding="utf-8")
        meta = SCROLLER.with_name(SCROLLER.name + ".meta").read_text(encoding="utf-8")

        self.assertIn("public sealed class PrototypeBackgroundScroller", source)
        self.assertIn("Camera.main", source)
        guid = re.search(r"^guid: (\w+)$", meta, re.MULTILINE).group(1)
        other_guids = [
            match.group(1)
            for path in TEMPLATE_ROOT.rglob("*.meta")
            if path.name != SCROLLER.name + ".meta"
            for match in [
                re.search(r"^guid: (\w+)$", path.read_text(encoding="utf-8"), re.MULTILINE)
            ]
            if match
        ]
        self.assertNotIn(guid, other_guids)

    def test_platformer_draw_order_puts_player_in_front(self) -> None:
        assembler = ASSEMBLER.read_text(encoding="utf-8")
        orders = {
            name: int(value)
            for name, value in re.findall(r"const int (\w+SortingOrder) = (-?\d+);", assembler)
        }

        self.assertLess(orders["PlatformSortingOrder"], orders["LandmarkSortingOrder"])
        self.assertLess(orders["LandmarkSortingOrder"], orders["PickupSortingOrder"])
        self.assertLess(orders["PickupSortingOrder"], orders["EnemySortingOrder"])
        self.assertLess(orders["EnemySortingOrder"], orders["PlayerSortingOrder"])


if __name__ == "__main__":
    unittest.main()

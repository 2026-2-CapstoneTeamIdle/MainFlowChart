from __future__ import annotations

import io
import re
import unittest
from pathlib import Path

from PIL import Image

from game_pipeline.asset_specs import build_image_generation_spec
from mainflow.image_backends import postprocess
from mainflow.image_generation import ImageAssetPlan, ImageRequest

ASSEMBLER = (
    Path(__file__).resolve().parent.parent
    / "unity_template/Assets/GameTemplate/Editor/PrefabSceneAssembler.cs"
)


def _request(asset_id: str, style: str) -> ImageRequest:
    spec = build_image_generation_spec("수집물", "반짝이는 보석 아이템", asset_id)
    plan = ImageAssetPlan(
        asset_id=asset_id,
        purpose="수집물",
        description="반짝이는 보석 아이템",
        required=False,
        filename=f"{asset_id}.png",
        unity_binding_key=f"asset_registry:{asset_id}",
        kind=spec["kind"],
        generation_spec=spec,
    )
    return ImageRequest(
        plan=plan,
        style=style,
        mood_style="Fantasy",
        viewpoint="사이드뷰",
        genre="Platformer",
        width=spec["width"],
        height=spec["height"],
        prompt="test",
    )


def _small_object_with_faint_haze() -> bytes:
    """A 1024 canvas: faint alpha haze everywhere and a small solid object in the middle."""

    image = Image.new("RGBA", (1024, 1024), (200, 200, 255, 6))
    image.paste((240, 200, 60, 255), (448, 448, 576, 576))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class ObjectSpriteFillTest(unittest.TestCase):
    def test_faint_haze_does_not_shrink_the_object(self) -> None:
        for style in ("Pixel Art", "Cartoon"):
            with self.subTest(style=style):
                request = _request("platformer_collectible", style)

                result = Image.open(
                    io.BytesIO(postprocess(_small_object_with_faint_haze(), request))
                )
                visible = result.getchannel("A").point(lambda value: 255 if value >= 128 else 0)
                left, top, right, bottom = visible.getbbox()

                # The object fills the canvas minus the 8% margin, not 1/8 of it.
                self.assertGreaterEqual((right - left) / result.width, 0.75)
                self.assertGreaterEqual((bottom - top) / result.height, 0.75)

    def test_platformer_landmark_markers_are_not_drawn(self) -> None:
        assembler = ASSEMBLER.read_text(encoding="utf-8")
        skip = re.search(
            r'entity\.archetype == "landmark"\s*&&\s*\((?P<genres>[^;]*?)\)\s*\)', assembler
        )

        self.assertIsNotNone(skip)
        self.assertIn('"Platformer"', skip.group("genres"))
        self.assertIn('"TowerDefense"', skip.group("genres"))


if __name__ == "__main__":
    unittest.main()

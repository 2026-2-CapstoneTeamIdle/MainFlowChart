from __future__ import annotations

import copy
import io
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from PIL import Image, ImageDraw

from mainflow.ArtifactManager import ArtifactManager
from mainflow.image_generation import (
    ANIMATION_BASE_POSE_PROMPT,
    SPRITE_SHEET_NOTE_PREFIX,
    ImageRequest,
    build_prompt,
    plan_assets,
)
from mainflow.image_spritesheet import (
    GENRE_ANIMATIONS,
    AnimationSpec,
    animations_for,
    build_sprite_sheet,
    sheet_mode,
    split_strip,
    validate_sheet,
)
from mainflow.nodes import generate_image_node, validate_image_node
from tests.image_fixtures import asset_item, image_asset_request, write_image_inputs

PLATFORMER = GENRE_ANIMATIONS["Platformer"]
SKIN, ROBE, BOOT, HAT = (
    (250, 210, 170, 255),
    (40, 90, 200, 255),
    (90, 50, 30, 255),
    (30, 50, 120, 255),
)


def draw_character(size: int = 64, legs: int = 0, scale: int = 1) -> Image.Image:
    """A small pixel-art character with hat, head, robe, arm and two legs."""

    image = Image.new("RGBA", (size * scale, size * scale))
    draw = ImageDraw.Draw(image)

    def box(x0: int, y0: int, x1: int, y1: int, color: tuple[int, int, int, int]) -> None:
        draw.rectangle((x0 * scale, y0 * scale, x1 * scale - 1, y1 * scale - 1), fill=color)

    box(22, 6, 42, 14, HAT)
    box(24, 14, 40, 28, SKIN)
    box(22, 28, 42, 46, ROBE)
    box(42, 32, 50, 36, SKIN)
    box(25 - legs, 46, 31 - legs, 60, BOOT)
    box(33 + legs, 46, 39 + legs, 60, BOOT)
    return image


def to_png(image: Image.Image) -> bytes:
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def player_plan():
    return plan_assets(image_asset_request())[0]


class FakeStrips:
    """Draws animation strips like an image model would, with switchable defects."""

    def __init__(self, defect: str | None = None) -> None:
        self.defect = defect
        self.calls: list[str] = []

    def __call__(self, animation: AnimationSpec) -> bytes:
        self.calls.append(animation.name)
        if self.defect == "error":
            raise RuntimeError("model unavailable")
        count = len(animation.keyframes)
        strip = Image.new("RGBA", (1536, 1024), (255, 255, 255, 255))
        slot = 1536 // count
        for index in range(count):
            pose = draw_character(legs=(index % 3) * 3, scale=4)
            pose = pose.crop(pose.getchannel("A").getbbox())
            if self.defect == "colors":
                pose = Image.merge(
                    "RGBA",
                    (*Image.new("RGB", pose.size, (0, 255, 0)).split(), pose.getchannel("A")),
                )
            jitter = 1 + 0.06 * ((index % 2) * 2 - 1)  # +-6% drawing jitter
            pose = pose.resize((round(pose.width * jitter), round(pose.height * jitter)))
            x = index * slot + (slot - pose.width) // 2
            if self.defect == "overlap":
                x = index * (pose.width // 2)  # each pose covers half of the previous one
            strip.alpha_composite(pose, (max(0, x), 900 - pose.height))
        if self.defect == "touching":
            draw = ImageDraw.Draw(strip)
            for index in range(1, count):
                # a thin staff tip bridging neighbouring frames
                draw.rectangle(
                    (index * slot - 30, 700, index * slot + 30, 703), fill=(90, 50, 30, 255)
                )
        return to_png(strip.convert("RGB"))


def frame_boxes(
    sheet_png: bytes, metadata: dict[str, Any]
) -> dict[str, list[tuple[int, int, int, int]]]:
    with Image.open(io.BytesIO(sheet_png)) as source:
        sheet = source.convert("RGBA")
    width, height = metadata["frame_width"], metadata["frame_height"]
    boxes: dict[str, list[tuple[int, int, int, int]]] = {}
    for name, animation in metadata["animations"].items():
        top = animation["row"] * height
        boxes[name] = [
            sheet.crop((i * width, top, (i + 1) * width, top + height)).getchannel("A").getbbox()
            for i in range(animation["frames"])
        ]
    return boxes


def colors(png: bytes) -> set[tuple[int, int, int]]:
    with Image.open(io.BytesIO(png)) as image:
        return {pixel[:3] for pixel in image.convert("RGBA").get_flattened_data() if pixel[3]}


class AnimationSelectionTest(unittest.TestCase):
    def test_only_character_sprites_in_animated_genres_get_sheets(self) -> None:
        request = image_asset_request(
            [
                asset_item("hero", "플레이어", "좌우 이동과 점프 캐릭터 스프라이트"),
                asset_item("slime", "적", "플레이어를 추적하는 적 스프라이트"),
                asset_item("feather", "공격", "날개에서 발사되는 깃털 투사체"),
                asset_item("ground", "맵", "발판과 지형 타일셋"),
            ]
        )
        names = {
            plan.asset_id: [a.name for a in animations_for(plan, "Platformer")]
            for plan in plan_assets(request)
        }
        self.assertEqual(
            names,
            {
                "hero": ["idle", "run", "jump"],
                "slime": ["idle", "run", "jump"],
                "feather": [],
                "ground": [],
            },
        )
        self.assertEqual(
            [a.name for a in animations_for(plan_assets(request)[0], "SurvivorLike")],
            ["idle", "walk", "hit"],
        )
        self.assertEqual(animations_for(plan_assets(request)[0], "CardGame"), ())

    def test_animated_characters_ask_for_an_animatable_base_pose(self) -> None:
        request = image_asset_request()
        player, tileset = plan_assets(request)
        self.assertIn(ANIMATION_BASE_POSE_PROMPT, build_prompt(player, request))
        self.assertNotIn(ANIMATION_BASE_POSE_PROMPT, build_prompt(tileset, request))

    def test_sheet_mode_setting(self) -> None:
        with mock.patch.dict(os.environ, {"MAINFLOW_IMAGE_SPRITE_SHEET_MODE": ""}):
            self.assertEqual(sheet_mode(), "auto")
        with mock.patch.dict(os.environ, {"MAINFLOW_IMAGE_SPRITE_SHEET_MODE": "AI"}):
            self.assertEqual(sheet_mode(), "ai")
        with mock.patch.dict(os.environ, {"MAINFLOW_IMAGE_SPRITE_SHEET_MODE": "magic"}):
            with self.assertRaises(ValueError):
                sheet_mode()


class TransformSheetTest(unittest.TestCase):
    def setUp(self) -> None:
        self.base = to_png(draw_character())
        self.sheet, self.metadata = build_sprite_sheet(
            self.base, player_plan(), PLATFORMER, "Pixel Art"
        )

    def test_grid_and_metadata(self) -> None:
        with Image.open(io.BytesIO(self.sheet)) as image:
            self.assertEqual(image.size, (6 * 64, 3 * 64))
        self.assertEqual(self.metadata["pivot"], [0.5, 0.0])
        self.assertEqual(self.metadata["unity_binding_key"], "asset_registry:platformer_player")
        self.assertEqual(
            self.metadata["animations"],
            {
                "idle": {"row": 0, "frames": 4, "fps": 6, "loop": True, "source": "transform"},
                "run": {"row": 1, "frames": 6, "fps": 12, "loop": True, "source": "transform"},
                "jump": {"row": 2, "frames": 3, "fps": 10, "loop": False, "source": "transform"},
            },
        )
        self.assertNotIn("fallbacks", self.metadata)
        self.assertEqual(validate_sheet(self.sheet, self.metadata), [])

    def test_pixel_art_is_never_resampled(self) -> None:
        # Integer pixel operations only: no blended or new colors appear.
        self.assertLessEqual(colors(self.sheet), colors(self.base))

    def test_feet_and_vertical_motion(self) -> None:
        boxes = frame_boxes(self.sheet, self.metadata)
        self.assertTrue(all(box[3] == 64 for box in boxes["idle"]))
        self.assertEqual(boxes["run"][0][3], 64)  # contact
        self.assertLess(boxes["run"][2][3], 64)  # passing, lifted
        self.assertEqual(boxes["jump"][0][3], 64)  # crouch
        self.assertLessEqual(boxes["jump"][1][3], 64 - 8)  # airborne
        self.assertEqual(boxes["jump"][2][3], 64)  # landing
        self.assertLess(boxes["jump"][0][3] - boxes["jump"][0][1], 54)  # crouch is shorter

    def test_run_legs_spread_and_close(self) -> None:
        with Image.open(io.BytesIO(self.sheet)) as source:
            sheet = source.convert("RGBA")

        def leg_span(column: int) -> int:
            legs = sheet.crop((column * 64, 64 + 56, column * 64 + 64, 64 + 64))
            box = legs.getchannel("A").getbbox()
            return box[2] - box[0]

        self.assertGreater(leg_span(0), leg_span(2))  # contact wider than passing


class AiSheetTest(unittest.TestCase):
    def setUp(self) -> None:
        self.base = to_png(draw_character())

    def build(self, strips: FakeStrips, style: str = "Pixel Art"):
        return build_sprite_sheet(self.base, player_plan(), PLATFORMER, style, strips)

    def test_strips_become_aligned_frames_in_the_base_palette(self) -> None:
        strips = FakeStrips()
        sheet, metadata = self.build(strips)

        self.assertEqual(strips.calls, ["idle", "run", "jump"])
        self.assertEqual({a["source"] for a in metadata["animations"].values()}, {"ai"})
        self.assertLessEqual(colors(sheet), colors(self.base))
        self.assertEqual(validate_sheet(sheet, metadata), [])
        boxes = frame_boxes(sheet, metadata)
        heights = {box[3] - box[1] for box in boxes["idle"]}
        self.assertLessEqual(max(heights) - min(heights), 1)  # jitter normalized
        self.assertTrue(all(box[3] == 64 for box in boxes["idle"]))  # feet on the floor
        self.assertLess(boxes["jump"][1][3], 64)  # airborne frame lifted
        for frames in boxes.values():
            for box in frames:
                self.assertGreater(box[0], 0)  # nothing clipped at the sides
                self.assertLess(box[2], 64)

    def test_touching_frames_are_split_at_the_thin_bridge(self) -> None:
        _, metadata = self.build(FakeStrips("touching"))
        self.assertEqual({a["source"] for a in metadata["animations"].values()}, {"ai"})

    def test_bad_strips_fall_back_to_transform_per_animation(self) -> None:
        for defect, reason in (
            ("overlap", "expected"),
            ("colors", "colors differ"),
            ("error", "model unavailable"),
        ):
            with self.subTest(defect=defect):
                sheet, metadata = self.build(FakeStrips(defect))
                self.assertEqual(
                    {a["source"] for a in metadata["animations"].values()}, {"transform"}
                )
                self.assertIn(reason, metadata["fallbacks"]["run"])
                self.assertEqual(validate_sheet(sheet, metadata), [])

    def test_split_strip_on_evenly_spaced_frames(self) -> None:
        with Image.open(io.BytesIO(FakeStrips()(PLATFORMER[1]))) as strip:
            strip = strip.convert("RGBA")
        strip.putalpha(Image.eval(strip.convert("L"), lambda v: 0 if v > 250 else 255))
        self.assertEqual(len(split_strip(strip, 6)), 6)


class ValidateSheetTest(unittest.TestCase):
    def setUp(self) -> None:
        self.sheet, self.metadata = build_sprite_sheet(
            to_png(draw_character()), player_plan(), PLATFORMER, "Pixel Art"
        )

    def test_grid_size_mismatch(self) -> None:
        metadata = {**self.metadata, "columns": 7}
        self.assertEqual(validate_sheet(self.sheet, metadata)[0][0], "image-sprite-sheet")

    def test_declared_frame_that_is_empty(self) -> None:
        metadata = copy.deepcopy(self.metadata)
        metadata["animations"]["jump"]["frames"] = 4
        problems = validate_sheet(self.sheet, metadata)
        self.assertEqual(len(problems), 1)
        self.assertIn("jump 4번", problems[0][1])

    def test_inconsistent_character_height(self) -> None:
        with Image.open(io.BytesIO(self.sheet)) as source:
            sheet = source.convert("RGBA")
        frame = sheet.crop((192, 0, 256, 64))
        small = frame.resize((21, 21))
        sheet.paste(Image.new("RGBA", (64, 64)), (192, 0))
        sheet.paste(small, (213, 43))
        problems = validate_sheet(to_png(sheet), self.metadata)
        self.assertTrue(any("idle 4번" in message for _, message in problems))


class StripGenerator:
    """A generator with ai strip support, like OpenAIImageGenerator."""

    name = "fake-ai"

    def __init__(self) -> None:
        self.strips = FakeStrips()
        self.references: list[bytes] = []

    def generate(self, request: ImageRequest) -> bytes:
        return to_png(draw_character(request.width))

    def generate_animation_strip(self, request, base_png, animation, frames, description):
        self.references.append(base_png)
        spec = next(spec for spec in PLATFORMER if spec.name == animation)
        assert frames == len(spec.keyframes) and description == spec.ai_description
        return self.strips(spec)


class SpriteSheetNodeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        workspace = Path(self.temporary_directory.name) / "workspace"
        self.environment = mock.patch.dict(
            os.environ,
            {
                "MAINFLOW_WORKSPACE": str(workspace),
                "MAINFLOW_IMAGE_BACKEND": "placeholder",
                "MAINFLOW_IMAGE_SPRITE_SHEETS": "on",
                "MAINFLOW_IMAGE_SPRITE_SHEET_MODE": "auto",
            },
        )
        self.environment.start()
        self.manager = ArtifactManager()
        self.project_id = self.manager.create_project()

    def tearDown(self) -> None:
        self.environment.stop()
        self.temporary_directory.cleanup()

    def _run(self, generator=None):
        state = write_image_inputs(self.manager, self.project_id, image_asset_request())
        state["image_draft"] = generate_image_node(state, generator)["image_draft"]
        return state

    def _sheet(self, state) -> tuple[dict[str, Any], dict[str, Any]]:
        draft = self.manager.read_json(state["image_draft"])
        (note,) = [n for n in draft["notes"] if n.startswith(SPRITE_SHEET_NOTE_PREFIX)]
        sheet_id, metadata_id = note.split("=")[1].split(",")
        metadata = self.manager.read_json(self.manager.get_artifact(self.project_id, metadata_id))
        return draft, metadata

    def test_placeholder_backend_uses_transform(self) -> None:
        state = self._run()
        _, metadata = self._sheet(state)
        self.assertEqual({a["source"] for a in metadata["animations"].values()}, {"transform"})
        self.assertEqual(
            metadata["sheet_relative_path"], "generated/images/platformer_player_sheet.png"
        )
        result = self.manager.read_json(validate_image_node(state)["image_validation_result"])
        self.assertEqual(result["status"], "passed", result["issues"])

    def test_strip_capable_backend_uses_ai_frames(self) -> None:
        generator = StripGenerator()
        state = self._run(generator)
        draft, metadata = self._sheet(state)
        self.assertEqual({a["source"] for a in metadata["animations"].values()}, {"ai"})
        # The 64px sprite is enlarged pixel-exactly before it is used as a reference.
        with Image.open(io.BytesIO(generator.references[0])) as reference:
            self.assertEqual(reference.size, (512, 512))
        self.assertEqual(
            [a["asset_id"] for a in draft["assets"]], ["platformer_player", "platformer_tileset"]
        )
        result = self.manager.read_json(validate_image_node(state)["image_validation_result"])
        self.assertEqual(result["status"], "passed", result["issues"])

    def test_transform_mode_skips_ai(self) -> None:
        os.environ["MAINFLOW_IMAGE_SPRITE_SHEET_MODE"] = "transform"
        generator = StripGenerator()
        _, metadata = self._sheet(self._run(generator))
        self.assertEqual(generator.strips.calls, [])
        self.assertEqual({a["source"] for a in metadata["animations"].values()}, {"transform"})

    def test_ai_mode_without_support_is_noted(self) -> None:
        os.environ["MAINFLOW_IMAGE_SPRITE_SHEET_MODE"] = "ai"
        draft, _ = self._sheet(self._run())
        self.assertTrue(
            any("AI 스프라이트 시트를 지원하지 않아" in note for note in draft["notes"])
        )

    def test_tampered_sheet_fails_only_that_asset(self) -> None:
        state = self._run()
        project_root = self.manager.ensure_project(self.project_id)
        (project_root / "generated/images/platformer_player_sheet.png").write_bytes(b"broken")
        result = self.manager.read_json(validate_image_node(state)["image_validation_result"])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["validated_asset_ids"], ["platformer_tileset"])

    def test_sheets_can_be_turned_off(self) -> None:
        os.environ["MAINFLOW_IMAGE_SPRITE_SHEETS"] = "off"
        state = self._run()
        draft = self.manager.read_json(state["image_draft"])
        self.assertFalse(any(n.startswith(SPRITE_SHEET_NOTE_PREFIX) for n in draft["notes"]))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import copy
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from mainflow.ArtifactManager import ArtifactManager
from mainflow.image_generation import (
    SPRITE_SHEET_NOTE_PREFIX,
    ImageRequest,
    PlaceholderImageGenerator,
    plan_assets,
)
from mainflow.image_spritesheet import (
    GENRE_ANIMATIONS,
    animations_for,
    build_sprite_sheet,
    validate_sheet,
)
from mainflow.nodes import generate_image_node, validate_image_node
from tests.image_fixtures import asset_item, image_asset_request, write_image_inputs

PLATFORMER = GENRE_ANIMATIONS["Platformer"]


def player_plan():
    return plan_assets(image_asset_request())[0]


def base_sprite(style: str = "Cartoon") -> bytes:
    plan = player_plan()
    return PlaceholderImageGenerator().generate(
        ImageRequest(plan, style, "Fantasy", "사이드뷰", "Platformer", 64, 64, "p")  # type: ignore[arg-type]
    )


def frame_boxes(sheet_png: bytes, metadata: dict) -> dict[str, list[tuple[int, int, int, int]]]:
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


class BuildSpriteSheetTest(unittest.TestCase):
    def test_sheet_grid_and_metadata(self) -> None:
        sheet, metadata = build_sprite_sheet(base_sprite(), player_plan(), PLATFORMER, "Cartoon")
        with Image.open(io.BytesIO(sheet)) as image:
            self.assertEqual(image.size, (6 * 64, 3 * 64))
        self.assertEqual((metadata["columns"], metadata["rows"]), (6, 3))
        self.assertEqual(metadata["pivot"], [0.5, 0.0])
        self.assertEqual(metadata["unity_binding_key"], "asset_registry:platformer_player")
        self.assertEqual(
            metadata["animations"],
            {
                "idle": {"row": 0, "frames": 4, "fps": 6, "loop": True},
                "run": {"row": 1, "frames": 6, "fps": 12, "loop": True},
                "jump": {"row": 2, "frames": 3, "fps": 10, "loop": False},
            },
        )
        self.assertEqual(validate_sheet(sheet, metadata), [])

    def test_feet_stay_on_the_floor_except_airborne_frames(self) -> None:
        sheet, metadata = build_sprite_sheet(base_sprite(), player_plan(), PLATFORMER, "Cartoon")
        boxes = frame_boxes(sheet, metadata)
        for box in boxes["idle"]:
            self.assertEqual(box[3], 64)
        # Run contact frames touch the floor, bounce frames are lifted.
        self.assertEqual(boxes["run"][0][3], 64)
        self.assertLess(boxes["run"][2][3], 64)
        # Jump: crouch and landing on the floor, airborne frame lifted, never clipped at the top.
        self.assertEqual(boxes["jump"][0][3], 64)
        self.assertLess(boxes["jump"][1][3], 60)
        self.assertEqual(boxes["jump"][2][3], 64)
        for frames in boxes.values():
            for box in frames:
                self.assertGreaterEqual(box[1], 0)

    def test_pixel_art_sheet_shares_one_palette_and_hard_alpha(self) -> None:
        sheet, _ = build_sprite_sheet(
            base_sprite("Pixel Art"), player_plan(), PLATFORMER, "Pixel Art"
        )
        with Image.open(io.BytesIO(sheet)) as image:
            pixels = list(image.convert("RGBA").get_flattened_data())
        self.assertLessEqual(len({pixel[:3] for pixel in pixels if pixel[3]}), 32)
        self.assertLessEqual({pixel[3] for pixel in pixels}, {0, 255})

    def test_empty_base_sprite_is_rejected(self) -> None:
        empty = io.BytesIO()
        Image.new("RGBA", (64, 64)).save(empty, format="PNG")
        with self.assertRaises(ValueError):
            build_sprite_sheet(empty.getvalue(), player_plan(), PLATFORMER, "Cartoon")


class ValidateSheetTest(unittest.TestCase):
    def setUp(self) -> None:
        self.sheet, self.metadata = build_sprite_sheet(
            base_sprite(), player_plan(), PLATFORMER, "Cartoon"
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
        # Shrink the last idle frame's character to a third of its size.
        frame = sheet.crop((192, 0, 256, 64))
        small = frame.resize((21, 21))
        sheet.paste(Image.new("RGBA", (64, 64)), (192, 0))
        sheet.paste(small, (213, 43))
        output = io.BytesIO()
        sheet.save(output, format="PNG")
        problems = validate_sheet(output.getvalue(), self.metadata)
        self.assertTrue(any("idle 4번" in message for _, message in problems))


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
            },
        )
        self.environment.start()
        self.manager = ArtifactManager()
        self.project_id = self.manager.create_project()

    def tearDown(self) -> None:
        self.environment.stop()
        self.temporary_directory.cleanup()

    def _run(self):
        state = write_image_inputs(self.manager, self.project_id, image_asset_request())
        state["image_draft"] = generate_image_node(state)["image_draft"]
        return state

    def _sheet_notes(self, state) -> list[str]:
        draft = self.manager.read_json(state["image_draft"])
        return [note for note in draft["notes"] if note.startswith(SPRITE_SHEET_NOTE_PREFIX)]

    def test_player_sheet_is_generated_and_validated(self) -> None:
        state = self._run()
        (note,) = self._sheet_notes(state)
        self.assertTrue(note.startswith(f"{SPRITE_SHEET_NOTE_PREFIX}platformer_player="))
        sheet_id, metadata_id = note.split("=")[1].split(",")
        sheet = self.manager.get_artifact(self.project_id, sheet_id)
        metadata = self.manager.read_json(self.manager.get_artifact(self.project_id, metadata_id))
        self.assertEqual(sheet["relative_path"], "generated/images/platformer_player_sheet.png")
        self.assertEqual(metadata["sheet_relative_path"], sheet["relative_path"])

        draft = self.manager.read_json(state["image_draft"])
        # The sheet is an extra file; the requested assets stay unchanged.
        self.assertEqual(
            [asset["asset_id"] for asset in draft["assets"]],
            ["platformer_player", "platformer_tileset"],
        )
        result = self.manager.read_json(validate_image_node(state)["image_validation_result"])
        self.assertEqual(result["status"], "passed", result["issues"])
        self.assertIn(
            {"criterion_id": "image-sprite-sheet", "passed": True, "message": "통과"},
            result["checks"],
        )

    def test_tampered_sheet_fails_only_that_asset(self) -> None:
        state = self._run()
        project_root = self.manager.ensure_project(self.project_id)
        (project_root / "generated/images/platformer_player_sheet.png").write_bytes(b"broken")

        result = self.manager.read_json(validate_image_node(state)["image_validation_result"])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["validated_asset_ids"], ["platformer_tileset"])
        self.assertIn(
            ("image-sprite-sheet", "platformer_player"),
            {(issue["code"], issue.get("target_id")) for issue in result["issues"]},
        )

    def test_sheets_can_be_turned_off(self) -> None:
        os.environ["MAINFLOW_IMAGE_SPRITE_SHEETS"] = "off"
        state = self._run()
        self.assertEqual(self._sheet_notes(state), [])
        project_root = self.manager.ensure_project(self.project_id)
        self.assertFalse((project_root / "generated/images/platformer_player_sheet.png").exists())


if __name__ == "__main__":
    unittest.main()

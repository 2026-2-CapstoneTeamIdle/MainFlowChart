from __future__ import annotations

import os
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from typing import get_args
from unittest import mock

from ArtifactManager import ArtifactManager
from contracts import CONTRACT_VERSION, GameGenre, ImageStyle, QualityLevel
from image_generation import (
    PNG_SIGNATURE,
    ImageRequest,
    PlaceholderImageGenerator,
    asset_size,
    encode_png,
    image_criteria,
    inspect_png,
    plan_assets,
)
from langgraph_game_flow_skeleton import generate_image_node, validate_image_node


class FailingPlayerGenerator(PlaceholderImageGenerator):
    name = "failing-player"

    def generate(self, request: ImageRequest) -> bytes:
        if request.plan.key == "player":
            raise RuntimeError("backend timeout")
        return super().generate(request)


class PngHelperTest(unittest.TestCase):
    def test_encode_and_inspect_round_trip(self) -> None:
        rows = [[(255, 0, 0, 255), (0, 0, 0, 0)], [(0, 255, 0, 255)] * 2]
        info = inspect_png(encode_png(rows))
        self.assertEqual((info.width, info.height), (2, 2))
        self.assertTrue(info.has_alpha)
        self.assertTrue(info.has_transparent_pixel)

    def test_inspect_unfilters_rows(self) -> None:
        # 2x1 RGBA image encoded with the "Sub" filter; second pixel alpha 0.
        width, height = 2, 1
        filtered = bytes([1, 10, 20, 30, 255, 5, 5, 5, 1])  # 255 + 1 wraps to 0
        header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)

        def chunk(kind: bytes, data: bytes) -> bytes:
            crc = zlib.crc32(kind + data) & 0xFFFFFFFF
            return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)

        png = (
            PNG_SIGNATURE
            + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(filtered))
            + chunk(b"IEND", b"")
        )
        self.assertTrue(inspect_png(png).has_transparent_pixel)

    def test_inspect_rejects_corrupt_data(self) -> None:
        png = bytearray(encode_png([[(1, 2, 3, 255)]]))
        png[-20] ^= 0xFF
        with self.assertRaises(ValueError):
            inspect_png(bytes(png))
        with self.assertRaises(ValueError):
            inspect_png(b"not a png")


class AssetPlanTest(unittest.TestCase):
    def test_every_genre_has_unique_assets_with_background(self) -> None:
        for genre in get_args(GameGenre):
            plans = plan_assets(genre)
            ids = [plan.asset_id for plan in plans]
            self.assertEqual(len(ids), len(set(ids)), genre)
            self.assertIn("image-background", ids, genre)

    def test_placeholder_matches_requested_size_for_all_styles(self) -> None:
        generator = PlaceholderImageGenerator()
        for style in get_args(ImageStyle):
            for quality in get_args(QualityLevel):
                plan = plan_assets("Action")[0]
                width, height = asset_size(plan, quality)
                content = generator.generate(
                    ImageRequest(plan, style, "Action", width, height, "prompt")
                )
                info = inspect_png(content)
                self.assertEqual((info.width, info.height), (width, height))
                self.assertTrue(info.has_transparent_pixel)


class ImageNodeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        workspace = Path(self.temporary_directory.name) / "workspace"
        self.environment = mock.patch.dict(
            os.environ, {"MAINFLOW_WORKSPACE": str(workspace)}
        )
        self.environment.start()
        self.manager = ArtifactManager()
        self.project_id = self.manager.create_project()
        self.parsed_request = self.manager.write_json(
            self.project_id,
            "data",
            "parsed_request.json",
            {
                "contract_version": CONTRACT_VERSION,
                "image_style": "Pixel Art",
                "genre": "Platformer",
                "quality": "Low",
            },
            producer="test",
        )
        self.final_spec = self.manager.write_json(
            self.project_id,
            "validation",
            "initial_final_validation_spec.json",
            {
                "contract_version": CONTRACT_VERSION,
                "spec_id": "initial-final-validation",
                "criteria": [],
            },
            producer="test",
        )
        self.asset_spec = self.manager.write_json(
            self.project_id,
            "validation",
            "asset_validation_spec.json",
            {
                "contract_version": CONTRACT_VERSION,
                "spec_id": "asset-validation",
                "image_criteria": image_criteria(),
                "sound_criteria": [],
            },
            producer="test",
        )

    def tearDown(self) -> None:
        self.environment.stop()
        self.temporary_directory.cleanup()

    def _generate(self, generator=None):
        return generate_image_node(
            {
                "project_id": self.project_id,
                "parsed_request": self.parsed_request,
                "initial_final_validation_spec": self.final_spec,
            },
            generator,
        )["image_draft"]

    def _validate(self, image_draft):
        reference = validate_image_node(
            {
                "project_id": self.project_id,
                "parsed_request": self.parsed_request,
                "image_draft": image_draft,
                "asset_validation_spec": self.asset_spec,
            }
        )["image_validation_result"]
        return self.manager.read_json(reference)

    def test_generate_and_validate_all_planned_assets(self) -> None:
        draft_reference = self._generate()
        draft = self.manager.read_json(draft_reference)
        expected_ids = [plan.asset_id for plan in plan_assets("Platformer")]

        self.assertEqual(draft["status"], "generated")
        self.assertEqual([item["asset_id"] for item in draft["assets"]], expected_ids)
        for asset in draft["assets"]:
            self.assertEqual(asset["artifact"]["media_type"], "image/png")
            self.assertTrue(asset["artifact"]["relative_path"].startswith("generated/images/"))

        result = self._validate(draft_reference)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["validated_asset_ids"], expected_ids)
        self.assertTrue(all(check["passed"] for check in result["checks"]))

    def test_missing_asset_fails_validation(self) -> None:
        draft_reference = self._generate(FailingPlayerGenerator())
        draft = self.manager.read_json(draft_reference)
        self.assertTrue(any("backend timeout" in note for note in draft["notes"]))

        result = self._validate(draft_reference)
        self.assertEqual(result["status"], "failed")
        self.assertNotIn("image-player", result["validated_asset_ids"])
        self.assertIn(
            ("image-plan-complete", "image-player"),
            {(issue["code"], issue.get("target_id")) for issue in result["issues"]},
        )

    def test_tampered_file_fails_validation(self) -> None:
        draft_reference = self._generate()
        project_root = self.manager.ensure_project(self.project_id)
        (project_root / "generated/images/item_coin.png").write_bytes(b"tampered")

        result = self._validate(draft_reference)
        self.assertEqual(result["status"], "failed")
        self.assertNotIn("image-item_coin", result["validated_asset_ids"])
        self.assertIn("image-player", result["validated_asset_ids"])


if __name__ == "__main__":
    unittest.main()

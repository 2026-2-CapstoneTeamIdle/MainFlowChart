from __future__ import annotations

import os
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from typing import get_args
from unittest import mock

from mainflow.ArtifactManager import ArtifactManager
from mainflow.contracts import ImageStyle, MoodStyle, Viewpoint
from mainflow.image_generation import (
    BINDING_NOTE_PREFIX,
    KIND_SIZES,
    MISSING_REQUIRED_NOTE_PREFIX,
    PNG_SIGNATURE,
    TRANSPARENT_PROMPT,
    ImageRequest,
    PlaceholderImageGenerator,
    build_prompt,
    classify_kind,
    encode_png,
    inspect_png,
    plan_assets,
)
from mainflow.nodes import generate_image_node, validate_image_node
from tests.image_fixtures import asset_item, image_asset_request, write_image_inputs


class FailingPlayerGenerator(PlaceholderImageGenerator):
    name = "failing-player"

    def generate(self, request: ImageRequest) -> bytes:
        if request.plan.asset_id == "platformer_player":
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
        filtered = bytes([1, 10, 20, 30, 255, 5, 5, 5, 1])  # 255 + 1 wraps to 0
        header = struct.pack(">IIBBBBB", 2, 1, 8, 6, 0, 0, 0)

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
    def test_kind_comes_from_purpose_and_description(self) -> None:
        # Catalog entries from game_pipeline.design_catalog.
        cases = {
            ("플레이어", "좌우 이동과 점프 캐릭터 스프라이트"): "sprite",
            ("맵", "발판과 지형 타일셋"): "tileset",
            ("카드 UI", "카드 테두리와 배경 이미지"): "ui",
            ("카드 일러스트", "효과를 표현하는 카드 이미지"): "illustration",
            ("배경", "주요 장면 배경 이미지"): "background",
            ("캐릭터", "표정 변형이 가능한 캐릭터 초상화"): "portrait",
            ("공격", "날개에서 발사되는 깃털 투사체"): "sprite",
        }
        for (purpose, description), kind in cases.items():
            self.assertEqual(classify_kind(purpose, description), kind, purpose)

    def test_plan_keeps_ids_and_binding_keys(self) -> None:
        request = image_asset_request(
            [
                *image_asset_request()["assets"],
                {**asset_item("bgm", "음악", "x"), "asset_type": "sound"},
            ]
        )
        plans = plan_assets(request)
        self.assertEqual(
            [plan.asset_id for plan in plans], ["platformer_player", "platformer_tileset"]
        )
        self.assertEqual(plans[0].unity_binding_key, "asset_registry:platformer_player")
        self.assertEqual(plans[0].filename, "platformer_player.png")

    def test_prompt_uses_request_context(self) -> None:
        request = image_asset_request()
        prompt = build_prompt(plan_assets(request)[0], request)
        for expected in (
            "Sky Runner",
            "Platformer",
            "점프 캐릭터",
            "pixel art",
            "fantasy",
            "side view",
        ):
            self.assertIn(expected, prompt)
        self.assertIn(TRANSPARENT_PROMPT, prompt)
        self.assertIn("not based on any existing", prompt)

    def test_every_style_mood_and_viewpoint_builds_a_prompt(self) -> None:
        for style in get_args(ImageStyle):
            for mood in get_args(MoodStyle):
                for viewpoint in get_args(Viewpoint):
                    request = {
                        **image_asset_request(image_style=style),
                        "mood_style": mood,
                        "viewpoint": viewpoint,
                    }
                    build_prompt(plan_assets(request)[0], request)  # type: ignore[arg-type]

    def test_placeholder_matches_size_and_transparency_for_all_kinds(self) -> None:
        generator = PlaceholderImageGenerator()
        for kind, (width, height) in KIND_SIZES.items():
            plan = plan_assets(image_asset_request())[0]
            plan = type(plan)(**{**plan.__dict__, "kind": kind})
            content = generator.generate(
                ImageRequest(plan, "Custom", "Cozy", "탑다운", "Platformer", width, height, "p")
            )
            info = inspect_png(content)
            self.assertEqual((info.width, info.height), (width, height), kind)
            self.assertEqual(info.has_transparent_pixel, plan.transparent, kind)


class ImageNodeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        workspace = Path(self.temporary_directory.name) / "workspace"
        self.environment = mock.patch.dict(
            os.environ,
            {"MAINFLOW_WORKSPACE": str(workspace), "MAINFLOW_IMAGE_BACKEND": "placeholder"},
        )
        self.environment.start()
        self.manager = ArtifactManager()
        self.project_id = self.manager.create_project()

    def tearDown(self) -> None:
        self.environment.stop()
        self.temporary_directory.cleanup()

    def _run(self, request=None, generator=None):
        state = write_image_inputs(self.manager, self.project_id, request or image_asset_request())
        state["image_draft"] = generate_image_node(state, generator)["image_draft"]
        return state

    def _validate(self, state):
        reference = validate_image_node(state)["image_validation_result"]
        return self.manager.read_json(reference)

    def test_generate_and_validate_requested_assets(self) -> None:
        state = self._run()
        draft = self.manager.read_json(state["image_draft"])

        self.assertEqual(draft["status"], "generated")
        self.assertEqual(
            [item["asset_id"] for item in draft["assets"]],
            ["platformer_player", "platformer_tileset"],
        )
        for asset in draft["assets"]:
            self.assertEqual(asset["artifact"]["media_type"], "image/png")
            self.assertEqual(
                asset["artifact"]["relative_path"], f"generated/images/{asset['asset_id']}.png"
            )
        self.assertIn(
            f"{BINDING_NOTE_PREFIX}platformer_player=asset_registry:platformer_player",
            draft["notes"],
        )

        result = self._validate(state)
        self.assertEqual(result["status"], "passed", result["issues"])
        self.assertEqual(result["validated_asset_ids"], ["platformer_player", "platformer_tileset"])

    def test_missing_required_asset_fails_validation(self) -> None:
        state = self._run(generator=FailingPlayerGenerator())
        draft = self.manager.read_json(state["image_draft"])
        self.assertEqual(draft["status"], "failed")
        self.assertIn(f"{MISSING_REQUIRED_NOTE_PREFIX}platformer_player", draft["notes"])

        result = self._validate(state)
        self.assertEqual(result["status"], "failed")
        self.assertIn(
            ("image-plan-complete", "platformer_player"),
            {(issue["code"], issue.get("target_id")) for issue in result["issues"]},
        )

    def test_missing_optional_asset_does_not_fail(self) -> None:
        request = image_asset_request(
            [
                {**asset_item("platformer_player", "플레이어", "캐릭터"), "required": False},
                asset_item("platformer_tileset", "맵", "타일셋"),
            ]
        )
        state = self._run(request, FailingPlayerGenerator())
        self.assertEqual(self._validate(state)["status"], "passed")

    def test_tampered_file_fails_validation(self) -> None:
        state = self._run()
        project_root = self.manager.ensure_project(self.project_id)
        (project_root / "generated/images/platformer_tileset.png").write_bytes(b"tampered")

        result = self._validate(state)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["validated_asset_ids"], ["platformer_player"])


if __name__ == "__main__":
    unittest.main()

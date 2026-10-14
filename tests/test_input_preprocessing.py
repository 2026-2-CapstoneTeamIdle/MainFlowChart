from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from typing import get_args
from unittest.mock import patch

from mainflow.ArtifactManager import ArtifactManager
from mainflow.contracts import GameGenre, ImageStyle, MoodStyle, Viewpoint
from mainflow.nodes.parse_input import parse_input_node
from mainflow.nodes.user_input import user_input_node


class InputPreprocessingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.image_style = get_args(ImageStyle)[0]
        self.mood_style = get_args(MoodStyle)[0]
        self.genre = get_args(GameGenre)[0]
        self.viewpoint = get_args(Viewpoint)[0]

    def request(self, **overrides: object) -> dict[str, object]:
        request: dict[str, object] = {
            "image_style": self.image_style,
            "mood_style": self.mood_style,
            "genre": self.genre,
            "viewpoint": self.viewpoint,
            "condition": "  공격과 이동이 가능한 게임  ",
        }
        request.update(overrides)
        return request

    def test_user_input_returns_only_normalized_contract_fields(self) -> None:
        output = user_input_node(
            self.request(custom_image_path="unused.png")  # type: ignore[arg-type]
        )

        self.assertEqual(output["condition"], "공격과 이동이 가능한 게임")
        self.assertNotIn("custom_image_path", output)

    def test_user_input_rejects_invalid_or_incomplete_input(self) -> None:
        with self.assertRaisesRegex(ValueError, "image_style"):
            user_input_node({"image_style": "Unknown"})  # type: ignore[typeddict-item]

        with self.assertRaisesRegex(ValueError, "condition"):
            user_input_node(self.request(condition="   "))  # type: ignore[arg-type]

    def test_custom_style_requires_a_reference_path(self) -> None:
        with self.assertRaisesRegex(ValueError, "custom_image_path"):
            user_input_node(
                self.request(image_style="Custom")  # type: ignore[arg-type]
            )

    def test_parse_input_persists_the_normalized_request(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory) / "workspace"
            with patch.dict(os.environ, {"MAINFLOW_WORKSPACE": str(workspace)}):
                state = parse_input_node(self.request())  # type: ignore[arg-type]
                request = ArtifactManager().read_json(state["parsed_request"])

        self.assertEqual(request["image_style"], self.image_style)
        self.assertEqual(request["mood_style"], self.mood_style)
        self.assertEqual(request["genre"], self.genre)
        self.assertEqual(request["viewpoint"], self.viewpoint)
        self.assertEqual(request["condition"], "공격과 이동이 가능한 게임")
        self.assertIsNone(request["custom_image"])

    def test_parse_input_rejects_mismatched_custom_image_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            workspace = root / "workspace"
            reference = root / "reference.png"
            reference.write_bytes(b"not-a-png")

            with patch.dict(os.environ, {"MAINFLOW_WORKSPACE": str(workspace)}):
                with self.assertRaisesRegex(ValueError, "not PNG"):
                    parse_input_node(
                        self.request(
                            image_style="Custom",
                            custom_image_path=str(reference),
                        )  # type: ignore[arg-type]
                    )
            self.assertFalse(workspace.exists())


if __name__ == "__main__":
    unittest.main()

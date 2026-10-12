from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mainflow.ArtifactManager import ArtifactManager
from mainflow.nodes.analysis import analysis_node
from mainflow.nodes.logic_analysis import logic_analysis_node
from mainflow.nodes.parse_input import parse_input_node


class RequestAnalysisTest(unittest.TestCase):
    def test_analysis_extracts_features_and_logic_criteria(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory) / "workspace"
            with patch.dict(os.environ, {"MAINFLOW_WORKSPACE": str(workspace)}):
                state = parse_input_node(
                    {
                        "image_style": "Pixel Art",
                        "mood_style": "Fantasy",
                        "genre": "플랫포머",
                        "condition": "8방향 공격과 점프가 가능한 게임",
                    }
                )
                state.update(analysis_node(state))  # type: ignore[arg-type]
                state.update(logic_analysis_node(state))  # type: ignore[arg-type]

                manager = ArtifactManager()
                analysis = manager.read_json(state["analysis"])
                logic = manager.read_json(state["logic_analysis"])

                self.assertEqual(
                    [feature["name"] for feature in analysis["features"]],
                    ["8방향 공격", "점프"],
                )
                self.assertEqual(logic["genre"], "플랫포머")
                self.assertEqual(len(logic["criteria"]), 4)

    def test_custom_image_is_imported_as_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            workspace = root / "workspace"
            source = root / "reference.png"
            source.write_bytes(b"\x89PNG\r\n\x1a\nmock-image-data")

            with patch.dict(os.environ, {"MAINFLOW_WORKSPACE": str(workspace)}):
                state = parse_input_node(
                    {
                        "image_style": "Custom",
                        "mood_style": "Cyberpunk",
                        "genre": "뱀서류",
                        "condition": "자동 공격으로 성장하는 게임",
                        "custom_image_path": str(source),
                    }
                )
                manager = ArtifactManager()
                request = manager.read_json(state["parsed_request"])
                custom_reference = request["custom_image"]

                self.assertEqual(custom_reference["media_type"], "image/png")
                self.assertEqual(
                    custom_reference["relative_path"],
                    "generated/images/references/custom_style.png",
                )
                self.assertEqual(manager.read_bytes(custom_reference), source.read_bytes())


if __name__ == "__main__":
    unittest.main()

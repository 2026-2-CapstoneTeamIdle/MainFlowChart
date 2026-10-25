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
                        "viewpoint": "사이드뷰",
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
                self.assertEqual(logic["viewpoint"], "사이드뷰")
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
                        "viewpoint": "탑다운",
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

    def test_analysis_preserves_unknown_clause_for_dynamic_generation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory) / "workspace"
            with patch.dict(os.environ, {"MAINFLOW_WORKSPACE": str(workspace)}):
                state = parse_input_node(
                    {
                        "image_style": "Pixel Art",
                        "mood_style": "Fantasy",
                        "genre": "플랫포머",
                        "viewpoint": "사이드뷰",
                        "condition": "점프하고 벽을 타고 올라간다",
                    }
                )
                state.update(analysis_node(state))  # type: ignore[arg-type]
                analysis = ArtifactManager().read_json(state["analysis"])

                self.assertEqual(
                    [feature["name"] for feature in analysis["features"]],
                    ["점프", "벽 타기"],
                )
                self.assertEqual(
                    analysis["features"][1]["description"],
                    "플레이어가 벽을 감지하고 벽면을 따라 오르내릴 수 있다.",
                )

    def test_analysis_splits_connective_into_separate_dynamic_features(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory) / "workspace"
            with patch.dict(os.environ, {"MAINFLOW_WORKSPACE": str(workspace)}):
                state = parse_input_node(
                    {
                        "image_style": "Pixel Art",
                        "mood_style": "Fantasy",
                        "genre": "플랫포머",
                        "viewpoint": "사이드뷰",
                        "condition": "점프하고 벽을 타며 공중 대시를 사용할 수 있는 게임",
                    }
                )
                state.update(analysis_node(state))  # type: ignore[arg-type]
                analysis = ArtifactManager().read_json(state["analysis"])

        descriptions = [feature["description"] for feature in analysis["features"]]
        self.assertEqual(
            descriptions,
            [
                "플레이어가 점프할 수 있다.",
                "플레이어가 벽을 감지하고 벽면을 따라 오르내릴 수 있다.",
                "플레이어가 공중에서 입력 방향으로 제한된 횟수만큼 대시할 수 있다.",
            ],
        )

    def test_analysis_keeps_upgrade_lists_as_complete_sentences(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory) / "workspace"
            with patch.dict(os.environ, {"MAINFLOW_WORKSPACE": str(workspace)}):
                state = parse_input_node(
                    {
                        "image_style": "Pixel Art",
                        "mood_style": "Fantasy",
                        "genre": "뱀서류",
                        "viewpoint": "탑다운",
                        "condition": (
                            "특전으로 검의 개수, 크기, 회전속도와 플레이어의 이동속도, "
                            "최대체력을 강화할 수 있다. 일정 시간이 지나면 보스가 등장한다."
                        ),
                    }
                )
                state.update(analysis_node(state))  # type: ignore[arg-type]
                analysis = ArtifactManager().read_json(state["analysis"])

        descriptions = [feature["description"] for feature in analysis["features"]]
        self.assertNotIn("크기", descriptions)
        self.assertIn(
            "특전으로 검의 개수, 크기, 회전속도와 플레이어의 이동속도, 최대체력을 강화할 수 있다",
            descriptions,
        )
        self.assertIn("일정 시간이 지나면 보스가 등장한다", descriptions)


if __name__ == "__main__":
    unittest.main()

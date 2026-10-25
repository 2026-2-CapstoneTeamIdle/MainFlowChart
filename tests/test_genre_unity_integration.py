from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from game_pipeline import (
    UnityProjectGenerator,
    UnityProjectValidator,
    build_game_logic_design,
    normalize_game_spec,
)
from mainflow.contracts import CONTRACT_VERSION, GameLogicDraft, ParsedRequest


@unittest.skipUnless(
    os.environ.get("MAINFLOW_RUN_UNITY_INTEGRATION_TESTS") == "1",
    "Unity integration test is opt-in",
)
class GenreUnityIntegrationTest(unittest.TestCase):
    def test_tower_defense_runtime_loop(self) -> None:
        self._generate_and_validate("타워 디펜스", "TowerDefense", "탑다운")

    def test_survivor_like_runtime_loop(self) -> None:
        self._generate_and_validate("뱀서류", "SurvivorLike", "탑다운")

    def _generate_and_validate(self, input_genre: str, profile: str, viewpoint: str) -> None:
        request: ParsedRequest = {
            "contract_version": CONTRACT_VERSION,
            "image_style": "Pixel Art",
            "mood_style": "Fantasy",
            "genre": input_genre,
            "viewpoint": viewpoint,
            "condition": "장르의 핵심 플레이 루프가 실제로 동작하는 게임",
            "custom_image": None,
        }
        design = build_game_logic_design(normalize_game_spec(input_genre, {"viewpoint": viewpoint}))
        self.assertEqual(design["game_spec"]["genre"], profile)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "project" / "game" / "unity_project"
            generation = UnityProjectGenerator().generate(
                design,
                root,
                image_style=request["image_style"],
                mood_style=request["mood_style"],
                viewpoint=viewpoint,
            )
            draft: GameLogicDraft = {
                "contract_version": CONTRACT_VERSION,
                "draft_id": f"{profile.lower()}-integration",
                "status": "generated",
                "engine": "Unity",
                "entry_scene": "game/unity_project/Assets/Scenes/Bootstrap.unity",
                "source_artifacts": [],
                "required_image_asset_ids": [
                    item["asset_id"]
                    for item in design["game_spec"]["asset_requirements"]
                    if item["asset_type"] == "image"
                ],
                "required_sound_asset_ids": [
                    item["asset_id"]
                    for item in design["game_spec"]["asset_requirements"]
                    if item["asset_type"] == "sound"
                ],
                "notes": [],
            }
            outcome = UnityProjectValidator(mode="required").validate(
                generation.project_root,
                draft,
                request,
            )
            self.assertEqual(
                outcome.status,
                "passed",
                f"issues={outcome.issues}\nchecks={outcome.checks}\n" + outcome.unity_log[-8000:],
            )


if __name__ == "__main__":
    unittest.main()

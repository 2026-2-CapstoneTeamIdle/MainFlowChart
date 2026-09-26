from __future__ import annotations

import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

from ArtifactManager import ArtifactManager
from contracts import ArtifactCategory


class ArtifactManagerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary_directory.name) / "workspace"
        self.manager = ArtifactManager(self.workspace)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_project_ids_and_required_directories(self) -> None:
        first = self.manager.create_project(date(2026, 9, 26))
        second = self.manager.create_project(date(2026, 9, 26))

        self.assertEqual(first, "20260926_01")
        self.assertEqual(second, "20260926_02")
        for relative_directory in self.manager.PROJECT_DIRECTORIES:
            self.assertTrue((self.workspace / first / relative_directory).is_dir())

    def test_json_round_trip_and_manifest_lookup(self) -> None:
        project_id = self.manager.create_project(date(2026, 9, 26))
        payload = {"message": "Agent 간 전달", "items": [1, 2, 3]}

        reference = self.manager.write_json(
            project_id,
            "data",
            "sample.json",
            payload,
            producer="test_agent",
        )

        self.assertEqual(self.manager.read_json(reference), payload)
        self.assertEqual(
            self.manager.get_artifact(project_id, reference["artifact_id"]),
            reference,
        )
        self.assertEqual(self.manager.list_artifacts(project_id, "data"), [reference])

    def test_rejects_path_traversal(self) -> None:
        project_id = self.manager.create_project(date(2026, 9, 26))

        with self.assertRaises(ValueError):
            self.manager.write_text(
                project_id,
                "data",
                "../outside.txt",
                "blocked",
                producer="test_agent",
            )

    def test_detects_artifact_tampering(self) -> None:
        project_id = self.manager.create_project(date(2026, 9, 26))
        reference = self.manager.write_text(
            project_id,
            "validation",
            "result.txt",
            "original",
            producer="test_agent",
        )
        artifact_path = self.workspace / project_id / reference["relative_path"]
        artifact_path.write_text("tampered", encoding="utf-8")

        with self.assertRaises(ValueError):
            self.manager.read_text(reference)

    def test_parallel_agents_do_not_lose_manifest_entries(self) -> None:
        project_id = self.manager.create_project(date(2026, 9, 26))
        jobs: list[tuple[ArtifactCategory, str, str]] = [
            ("image", "image.json", "generate_image"),
            ("sound", "sound.json", "generate_sound"),
            ("game", "game.json", "design_game_logic"),
        ]

        def write(job: tuple[ArtifactCategory, str, str]) -> None:
            category, filename, producer = job
            self.manager.write_json(
                project_id,
                category,
                filename,
                {"producer": producer},
                producer=producer,
            )

        with ThreadPoolExecutor(max_workers=3) as executor:
            list(executor.map(write, jobs))

        self.assertEqual(len(self.manager.list_artifacts(project_id)), 3)


if __name__ == "__main__":
    unittest.main()

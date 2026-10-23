from __future__ import annotations

import hashlib
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from unittest.mock import patch

from mainflow.ArtifactManager import ArtifactManager
from mainflow.contracts import ArtifactCategory


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

    def test_rejects_path_traversal_and_detects_tampering(self) -> None:
        project_id = self.manager.create_project(date(2026, 9, 26))
        with self.assertRaises(ValueError):
            self.manager.write_text(
                project_id,
                "data",
                "../outside.txt",
                "blocked",
                producer="test_agent",
            )
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

    def test_parallel_manifest_updates(self) -> None:
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

    def test_windows_permission_error_on_existing_manifest_lock_is_retried(self) -> None:
        project_id = self.manager.create_project(date(2026, 9, 26))
        lock_path = self.workspace / project_id / self.manager.MANIFEST_LOCK_RELATIVE_PATH
        original_open = __import__("os").open
        calls = 0
        lock_path.write_text("other writer", encoding="utf-8")

        def open_with_windows_contention(path, flags, mode=0o777):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise PermissionError("sharing violation")
            return original_open(path, flags, mode)

        def release_lock(_seconds):
            lock_path.unlink(missing_ok=True)

        with (
            patch("mainflow.ArtifactManager.os.open", side_effect=open_with_windows_contention),
            patch("mainflow.ArtifactManager.time.sleep", side_effect=release_lock),
        ):
            with self.manager._manifest_lock(project_id):
                self.assertTrue(lock_path.exists())

        self.assertEqual(calls, 2)
        self.assertFalse(lock_path.exists())

    def test_windows_permission_error_after_lock_release_is_retried(self) -> None:
        project_id = self.manager.create_project(date(2026, 9, 26))
        original_open = __import__("os").open
        calls = 0

        def open_with_release_race(path, flags, mode=0o777):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise PermissionError("sharing violation after owner removed lock")
            return original_open(path, flags, mode)

        with (
            patch("mainflow.ArtifactManager.os.open", side_effect=open_with_release_race),
            patch("mainflow.ArtifactManager.time.sleep"),
        ):
            with self.manager._manifest_lock(project_id):
                pass

        self.assertEqual(calls, 2)

    def test_mutable_project_files_use_safe_paths_and_optimistic_locking(self) -> None:
        project_id = self.manager.create_project(date(2026, 9, 26))
        relative_path = "game/working/notes.txt"

        self.manager.write_project_text(project_id, relative_path, "first")
        first_hash = hashlib.sha256(b"first").hexdigest()
        self.manager.write_project_text(
            project_id,
            relative_path,
            "second",
            expected_sha256=first_hash,
        )

        self.assertEqual(self.manager.read_project_file(project_id, relative_path), b"second")
        self.assertIn(Path(relative_path), self.manager.list_project_files(project_id, "game"))
        with self.assertRaises(ValueError):
            self.manager.write_project_text(
                project_id,
                relative_path,
                "stale update",
                expected_sha256=first_hash,
            )
        with self.assertRaises(ValueError):
            self.manager.resolve_project_path(project_id, "../outside.txt")

    def test_mutable_project_files_cannot_replace_registered_artifacts(self) -> None:
        project_id = self.manager.create_project(date(2026, 9, 26))
        reference = self.manager.write_text(
            project_id,
            "data",
            "immutable.txt",
            "original",
            producer="test_agent",
        )
        with self.assertRaisesRegex(ValueError, "immutable"):
            self.manager.write_project_text(
                project_id,
                reference["relative_path"],
                "replacement",
                expected_sha256=reference["sha256"],
            )


if __name__ == "__main__":
    unittest.main()

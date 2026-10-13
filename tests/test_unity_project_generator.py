from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from io import BytesIO
from pathlib import Path
from typing import cast

from game_pipeline import (
    UnityProjectGenerator,
    build_game_logic_design,
    normalize_game_spec,
)
from mainflow.contracts import ArtifactReference, CONTRACT_VERSION


class UnityProjectGeneratorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.output_root = Path(self.temporary_directory.name)

    def test_generates_configured_ready_to_open_project(self) -> None:
        design = build_game_logic_design(normalize_game_spec("뱀서류"))
        generator = UnityProjectGenerator()

        result = generator.generate(
            design,
            self.output_root / "WingSurvivor",
            image_style="Anime",
            mood_style="Fantasy",
            viewpoint="탑다운",
        )

        self.assertTrue(result.entry_scene.is_file())
        self.assertTrue(result.manifest_path.is_file())
        self.assertTrue(result.build_request_path.is_file())
        self.assertTrue(result.image_asset_request_path.is_file())
        self.assertTrue(result.sound_asset_request_path.is_file())
        self.assertFalse((result.project_root / "Library").exists())
        config = (
            result.project_root / "Assets/GameTemplate/Generated/GameTemplateConfig.asset"
        ).read_text(encoding="utf-8")
        self.assertIn('genre: "SurvivorLike"', config)
        self.assertIn('viewpoint: "탑다운"', config)
        for module_id in design["selected_modules"]:
            self.assertIn(f'- "{module_id}"', config)

        manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["design_id"], design["design_id"])
        self.assertEqual(manifest["selected_modules"], design["selected_modules"])
        image_request = json.loads(result.image_asset_request_path.read_text(encoding="utf-8"))
        sound_request = json.loads(result.sound_asset_request_path.read_text(encoding="utf-8"))
        self.assertEqual(image_request["asset_type"], "image")
        self.assertEqual(image_request["image_style"], "Anime")
        self.assertEqual(image_request["viewpoint"], "탑다운")
        self.assertIsNone(image_request["reference_image"])
        self.assertEqual(sound_request["asset_type"], "sound")
        self.assertEqual(sound_request["image_style"], "Anime")
        self.assertTrue(image_request["assets"])
        self.assertTrue(sound_request["assets"])
        self.assertTrue(all(item["asset_type"] == "image" for item in image_request["assets"]))
        self.assertTrue(all(item["asset_type"] == "sound" for item in sound_request["assets"]))
        self.assertTrue(
            all(
                item["unity_binding_key"].startswith("asset_registry:")
                for item in image_request["assets"]
            )
        )

    def test_archive_is_deterministic_and_contains_unity_project(self) -> None:
        design = build_game_logic_design(normalize_game_spec("카드"))
        generator = UnityProjectGenerator()
        result = generator.generate(design, self.output_root / "CardGame")

        first_archive = generator.create_archive(result.project_root)
        second_archive = generator.create_archive(result.project_root)

        self.assertEqual(first_archive, second_archive)
        with zipfile.ZipFile(BytesIO(first_archive)) as archive:
            names = set(archive.namelist())
        self.assertIn("UnityProject/Packages/manifest.json", names)
        self.assertIn("UnityProject/ProjectSettings/ProjectVersion.txt", names)
        self.assertIn(
            "UnityProject/Assets/GameTemplate/Generated/GenerationRequest.json",
            names,
        )
        self.assertIn(
            "UnityProject/Assets/GameTemplate/Generated/AssetRequests/image_asset_request.json",
            names,
        )
        self.assertIn(
            "UnityProject/Assets/GameTemplate/Generated/AssetRequests/sound_asset_request.json",
            names,
        )

    def test_custom_reference_is_forwarded_only_to_image_request(self) -> None:
        design = build_game_logic_design(normalize_game_spec("비주얼 노벨"))
        reference = cast(
            ArtifactReference,
            {
                "contract_version": CONTRACT_VERSION,
                "artifact_id": "image-reference",
                "project_id": "20261013_01",
                "category": "image",
                "relative_path": "generated/images/references/custom_style.png",
                "media_type": "image/png",
                "size_bytes": 128,
                "sha256": "a" * 64,
                "created_at": "2026-10-13T00:00:00+00:00",
                "producer": "parse_input",
            },
        )

        result = UnityProjectGenerator().generate(
            design,
            self.output_root / "CustomVisualNovel",
            image_style="Custom",
            reference_image=reference,
        )
        image_request = json.loads(result.image_asset_request_path.read_text(encoding="utf-8"))
        sound_request = json.loads(result.sound_asset_request_path.read_text(encoding="utf-8"))

        self.assertEqual(image_request["reference_image"], reference)
        self.assertIsNone(sound_request["reference_image"])

    def test_rejects_existing_destination(self) -> None:
        destination = self.output_root / "Existing"
        destination.mkdir()
        design = build_game_logic_design(normalize_game_spec("플랫포머"))

        with self.assertRaises(FileExistsError):
            UnityProjectGenerator().generate(design, destination)


if __name__ == "__main__":
    unittest.main()

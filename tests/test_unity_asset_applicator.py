from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from typing import cast

from game_pipeline.unity_asset_applicator import UnityAssetApplicator
from mainflow.ArtifactManager import ArtifactManager
from mainflow.contracts import (
    CONTRACT_VERSION,
    AssetGenerationRequest,
    ImageDraft,
    ImageValidationResult,
    SoundDraft,
    SoundValidationResult,
)


class UnityAssetApplicatorTest(unittest.TestCase):
    def setUp(self) -> None:
        Path(".test-tmp").mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=".test-tmp")
        self.manager = ArtifactManager(self.temporary.name)
        self.project_id = self.manager.create_project(date(2026, 10, 16), sequence=1)
        self.manager.write_project_file(
            self.project_id,
            "game/unity_project/ProjectSettings/ProjectVersion.txt",
            b"m_EditorVersion: 6000.0.71f1\n",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_only_validated_assets_are_staged_and_described(self) -> None:
        image_artifact = self.manager.write_bytes(
            self.project_id,
            "image",
            "player.png",
            b"validated-png",
            producer="test",
            media_type="image/png",
        )
        rejected_artifact = self.manager.write_bytes(
            self.project_id,
            "image",
            "enemy.png",
            b"rejected-png",
            producer="test",
            media_type="image/png",
        )
        sound_artifact = self.manager.write_bytes(
            self.project_id,
            "sound",
            "bgm.ogg",
            b"validated-ogg",
            producer="test",
            media_type="audio/ogg",
        )
        image_request = cast(
            AssetGenerationRequest,
            {
                "contract_version": CONTRACT_VERSION,
                "request_id": "images",
                "source_design_id": "design",
                "game_title": "Test",
                "genre": "SurvivorLike",
                "asset_type": "image",
                "image_style": "Pixel Art",
                "mood_style": "Fantasy",
                "viewpoint": "탑다운",
                "reference_image": None,
                "output_directory": "generated/images",
                "assets": [
                    self._image_item("player_sprite", True),
                    self._image_item("enemy_sprite", True),
                ],
            },
        )
        sound_request = cast(
            AssetGenerationRequest,
            {
                "contract_version": CONTRACT_VERSION,
                "request_id": "sounds",
                "source_design_id": "design",
                "game_title": "Test",
                "genre": "SurvivorLike",
                "asset_type": "sound",
                "image_style": "Pixel Art",
                "mood_style": "Fantasy",
                "viewpoint": "탑다운",
                "reference_image": None,
                "output_directory": "generated/sounds",
                "assets": [self._sound_item("survivor_bgm")],
            },
        )
        image_draft = cast(
            ImageDraft,
            {
                "contract_version": CONTRACT_VERSION,
                "draft_id": "image-draft",
                "status": "generated",
                "assets": [
                    self._image_asset("player_sprite", image_artifact),
                    self._image_asset("enemy_sprite", rejected_artifact),
                ],
                "missing_required_asset_ids": [],
                "notes": [],
            },
        )
        sound_draft = cast(
            SoundDraft,
            {
                "contract_version": CONTRACT_VERSION,
                "draft_id": "sound-draft",
                "status": "generated",
                "assets": [
                    {
                        "asset_id": "survivor_bgm",
                        "name": "survivor_bgm.ogg",
                        "kind": "bgm",
                        "unity_binding_key": "asset_registry:survivor_bgm",
                        "artifact": sound_artifact,
                        "file_format": "ogg",
                        "duration_seconds": 90.0,
                        "loop": True,
                        "mixer_group": "Music",
                        "prompt": "test",
                    }
                ],
                "missing_required_asset_ids": [],
                "notes": [],
            },
        )
        corrected = self.manager.write_bytes(
            self.project_id,
            "sound",
            "processed/bgm.wav",
            b"corrected-wav",
            producer="validate_sound",
        )
        image_validation = cast(
            ImageValidationResult,
            {
                "contract_version": CONTRACT_VERSION,
                "status": "failed",
                "checks": [],
                "issues": [],
                "validated_asset_ids": ["player_sprite"],
            },
        )
        sound_validation = cast(
            SoundValidationResult,
            {
                "contract_version": CONTRACT_VERSION,
                "status": "passed",
                "checks": [],
                "issues": [],
                "validated_asset_ids": ["survivor_bgm"],
                "validated_assets": {
                    "manifest_version": "1.0.0",
                    "contract_version": CONTRACT_VERSION,
                    "assets": [
                        {
                            "asset_id": "survivor_bgm",
                            "asset_type": "sound",
                            "unity_binding_key": "asset_registry:survivor_bgm",
                            "artifact": corrected,
                            "file_format": "wav",
                        }
                    ],
                },
            },
        )

        result = UnityAssetApplicator(self.manager).apply(
            self.project_id,
            image_request,
            sound_request,
            image_draft,
            sound_draft,
            image_validation,
            sound_validation,
        )

        self.assertEqual(result.applied_image_asset_ids, ["player_sprite"])
        self.assertEqual(result.applied_sound_asset_ids, ["survivor_bgm"])
        self.assertEqual(result.manifest["missing_required_asset_ids"], ["enemy_sprite"])
        self.assertEqual(
            self.manager.read_project_file(
                self.project_id,
                "game/unity_project/Assets/GameTemplate/Generated/AppliedAssets/Images/player_sprite.png",
            ),
            b"validated-png",
        )
        self.assertFalse(
            self.manager.resolve_project_path(
                self.project_id,
                "game/unity_project/Assets/GameTemplate/Generated/AppliedAssets/Images/enemy_sprite.png",
            ).exists()
        )
        payload = json.loads(result.manifest_path.read_text(encoding="utf-8"))
        bgm = next(entry for entry in payload["entries"] if entry["asset_id"] == "survivor_bgm")
        self.assertTrue(bgm["unity_path"].endswith(".wav"))
        self.assertEqual(
            self.manager.read_project_file(
                self.project_id, "game/unity_project/" + bgm["unity_path"]
            ),
            b"corrected-wav",
        )
        self.assertTrue(bgm["loop"])
        self.assertEqual(bgm["unity_load_type"], "streaming")
        self.assertEqual(bgm["mixer_group"], "Music")

    @staticmethod
    def _image_item(asset_id: str, required: bool) -> dict[str, object]:
        return {
            "asset_id": asset_id,
            "asset_type": "image",
            "purpose": "test",
            "description": "test",
            "required": required,
            "suggested_filename": f"{asset_id}.png",
            "unity_binding_key": f"asset_registry:{asset_id}",
            "generation_spec": {
                "kind": "sprite",
                "width": 64,
                "height": 64,
                "transparent": True,
                "sprite_mode": "single",
                "pixels_per_unit": 32,
            },
        }

    @staticmethod
    def _sound_item(asset_id: str) -> dict[str, object]:
        return {
            "asset_id": asset_id,
            "asset_type": "sound",
            "purpose": "test",
            "description": "test",
            "required": True,
            "suggested_filename": f"{asset_id}.ogg",
            "unity_binding_key": f"asset_registry:{asset_id}",
            "generation_spec": {
                "kind": "bgm",
                "target_duration_seconds": 90.0,
                "loop": True,
                "channels": "stereo",
                "sample_rate_hz": 44100,
                "unity_load_type": "streaming",
                "mixer_group": "Music",
                "spatial_blend": 0.0,
            },
        }

    @staticmethod
    def _image_asset(asset_id: str, artifact: object) -> dict[str, object]:
        return {
            "asset_id": asset_id,
            "name": f"{asset_id}.png",
            "kind": "sprite",
            "unity_binding_key": f"asset_registry:{asset_id}",
            "artifact": artifact,
            "file_format": "png",
            "width": 64,
            "height": 64,
            "prompt": "test",
        }


if __name__ == "__main__":
    unittest.main()

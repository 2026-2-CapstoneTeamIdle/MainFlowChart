from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from typing import cast

from game_pipeline.asset_specs import build_sound_generation_spec, classify_sound_cue
from game_pipeline.design_catalog import GENRE_PRESETS
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
        self.assertEqual(bgm["audio_cue"], "scene_start")
        rebuild_request = self.manager.resolve_project_path(
            self.project_id,
            "game/unity_project/Assets/GameTemplate/Generated/GenerationRequest.json",
        )
        self.assertTrue(rebuild_request.is_file())
        self.assertEqual(
            set(json.loads(rebuild_request.read_text(encoding="utf-8"))["asset_ids"]),
            {"player_sprite", "survivor_bgm"},
        )

        placeholder_draft = cast(
            ImageDraft,
            {**image_draft, "notes": ["generator=placeholder"]},
        )
        placeholder_result = UnityAssetApplicator(self.manager).apply(
            self.project_id,
            image_request,
            sound_request,
            placeholder_draft,
            sound_draft,
            image_validation,
            sound_validation,
            exclude_placeholder_images=True,
        )
        self.assertEqual(placeholder_result.applied_image_asset_ids, [])
        self.assertEqual(
            placeholder_result.suppressed_placeholder_image_asset_ids,
            ["enemy_sprite", "player_sprite"],
        )
        self.assertEqual(placeholder_result.manifest["missing_required_asset_ids"], [])
        self.assertNotIn(
            "player_sprite",
            {entry["asset_id"] for entry in placeholder_result.manifest["entries"]},
        )
        self.assertIn(
            "Placeholder image assets",
            " ".join(placeholder_result.manifest["warnings"]),
        )

        skipped_result = UnityAssetApplicator(self.manager).apply(
            self.project_id,
            image_request,
            sound_request,
            image_draft,
            sound_draft,
            image_validation,
            sound_validation,
            skip_image_application=True,
        )
        self.assertEqual(skipped_result.applied_image_asset_ids, [])
        self.assertEqual(
            skipped_result.suppressed_placeholder_image_asset_ids,
            ["enemy_sprite", "player_sprite"],
        )
        self.assertEqual(skipped_result.manifest["missing_required_asset_ids"], [])
        self.assertEqual(
            {entry["asset_type"] for entry in skipped_result.manifest["entries"]},
            {"sound"},
        )
        self.assertIn(
            "Image application is disabled",
            " ".join(skipped_result.manifest["warnings"]),
        )

    def test_sound_cues_follow_purpose_and_description(self) -> None:
        cases = {
            ("배경음악", "스테이지 반복 배경음악"): "scene_start",
            ("배경음악", "승리 엔딩 음악"): "game_clear",
            ("배경음악", "패배 시 게임오버 음악"): "game_over",
            ("환경음", "숲 바람 소리"): "scene_start",
            ("점프", "짧은 점프 효과음"): "jump",
            ("공격", "타워 발사 효과음"): "attack",
            ("피격", "적의 공격에 맞았을 때"): "player_hit",
            ("효과음", "적 피격 효과음"): "enemy_hit",
            ("효과음", "player hurt"): "player_hit",
            # Partial-word matches that used to misfire (PR review).
            ("효과음", "타워 build 사운드"): "",
            ("효과음", "guitar 스트럼"): "",
            ("효과음", "clear하고 맑은 종소리"): "",
            ("효과음", "장애물을 피해 이동하는 소리"): "",
            ("효과음", "적 사망 효과음"): "",
            ("효과음", "stage clear fanfare"): "game_clear",
            ("카드 사용", "카드를 사용할 때의 효과음"): "card_play",
            ("UI", "선택지 결정 효과음"): "ui",
            ("행동", "행동 완료 효과음"): "activity",
            ("아이템", "코인 획득"): "pickup",
            ("tower_built feedback", "tower construction succeeds"): "tower_built",
            ("tower_upgraded feedback", "tower upgrade succeeds"): "tower_upgraded",
            ("enemy_defeated feedback", "enemy health reaches zero"): "enemy_defeated",
            ("base_damaged feedback", "enemy reaches base"): "base_damaged",
            ("wave_started feedback", "preparation expires"): "wave_started",
            ("boss_arrived feedback", "boss wave begins"): "boss_arrived",
            ("효과음", "알 수 없는 소리"): "",
        }
        for (purpose, description), expected in cases.items():
            generation_spec = build_sound_generation_spec(purpose, description)
            kind = generation_spec["kind"]
            with self.subTest(purpose=purpose, description=description):
                self.assertEqual(classify_sound_cue(purpose, description, kind), expected)
                self.assertEqual(generation_spec["audio_cue"], expected)

    def test_every_catalog_sound_has_a_cue(self) -> None:
        for genre, profile in GENRE_PRESETS.items():
            for item in profile["asset_requirements"]:
                if item["asset_type"] != "sound":
                    continue
                kind = build_sound_generation_spec(item["purpose"], item["description"])["kind"]
                with self.subTest(genre=genre, asset_id=item["asset_id"]):
                    self.assertTrue(classify_sound_cue(item["purpose"], item["description"], kind))

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

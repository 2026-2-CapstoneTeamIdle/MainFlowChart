from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from typing import cast
from unittest.mock import patch

from PIL import Image

from game_pipeline.asset_specs import (
    build_image_generation_spec,
    build_sound_generation_spec,
    classify_sound_cue,
)
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
from mainflow.nodes.apply_assets import image_application_enabled


def test_image_application_is_on_by_default_and_can_be_disabled() -> None:
    with patch.dict(os.environ, {}, clear=True):
        assert image_application_enabled()
    with patch.dict(os.environ, {"MAINFLOW_APPLY_IMAGE_ASSETS": "off"}):
        assert not image_application_enabled()


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

        # Diagnostic builds may add rejected drafts, but must keep normalized selections.
        diagnostic = UnityAssetApplicator(self.manager).apply(
            self.project_id,
            image_request,
            sound_request,
            image_draft,
            sound_draft,
            image_validation,
            sound_validation,
            include_unvalidated_drafts=True,
        )
        diagnostic_bgm = next(
            entry for entry in diagnostic.manifest["entries"] if entry["asset_id"] == "survivor_bgm"
        )
        self.assertTrue(diagnostic_bgm["unity_path"].endswith(".wav"))
        self.assertEqual(
            self.manager.read_project_file(
                self.project_id, "game/unity_project/" + diagnostic_bgm["unity_path"]
            ),
            b"corrected-wav",
        )
        self.assertEqual(diagnostic.applied_image_asset_ids, ["enemy_sprite", "player_sprite"])
        self.assertTrue(
            any("enemy_sprite" in warning for warning in diagnostic.manifest["warnings"])
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

    def test_validated_character_sheet_stages_runtime_frames_and_state_metadata(self) -> None:
        base = Image.new("RGBA", (4, 4), (20, 40, 60, 255))
        sheet = Image.new("RGBA", (8, 4), (0, 0, 0, 0))
        sheet.paste(base, (0, 0))
        sheet.paste(Image.new("RGBA", (4, 4), (80, 100, 120, 255)), (4, 0))

        def png(image: Image.Image) -> bytes:
            output = io.BytesIO()
            image.save(output, format="PNG")
            return output.getvalue()

        base_ref = self.manager.write_bytes(
            self.project_id, "image", "player.png", png(base), producer="test"
        )
        sheet_ref = self.manager.write_bytes(
            self.project_id, "image", "player_sheet.png", png(sheet), producer="test"
        )
        metadata_ref = self.manager.write_json(
            self.project_id,
            "image",
            "player_sheet.json",
            {
                "frame_width": 4,
                "frame_height": 4,
                "columns": 2,
                "rows": 1,
                "animations": {"idle": {"row": 0, "frames": 2, "fps": 6, "loop": True}},
            },
            producer="test",
        )
        image_asset = self._image_asset("player_sprite", base_ref)
        image_request = cast(
            AssetGenerationRequest,
            {
                "genre": "SurvivorLike",
                "asset_type": "image",
                "image_style": "Pixel Art",
                "assets": [self._image_item("player_sprite", True)],
            },
        )
        sound_request = cast(
            AssetGenerationRequest,
            {"genre": "SurvivorLike", "asset_type": "sound", "assets": []},
        )
        result = UnityAssetApplicator(self.manager).apply(
            self.project_id,
            image_request,
            sound_request,
            cast(
                ImageDraft,
                {
                    "assets": [image_asset],
                    "notes": [
                        f"sprite_sheet:player_sprite={sheet_ref['artifact_id']},"
                        f"{metadata_ref['artifact_id']}"
                    ],
                },
            ),
            cast(SoundDraft, {"assets": []}),
            cast(
                ImageValidationResult,
                {
                    "validated_asset_ids": ["player_sprite"],
                    "validated_assets": {
                        "manifest_version": "1.0.0",
                        "contract_version": CONTRACT_VERSION,
                        "assets": [
                            {
                                "asset_id": "player_sprite",
                                "asset_type": "image",
                                "unity_binding_key": "asset_registry:player_sprite",
                                "artifact": base_ref,
                                "file_format": "png",
                            }
                        ],
                    },
                },
            ),
            cast(
                SoundValidationResult,
                {
                    "validated_asset_ids": [],
                    "validated_assets": {
                        "manifest_version": "1.0.0",
                        "contract_version": CONTRACT_VERSION,
                        "assets": [],
                    },
                },
            ),
        )
        entry = result.manifest["entries"][0]
        self.assertTrue(entry["animation_sheet_path"].endswith("player_sprite_sheet.png"))
        staged = self.manager.read_project_file(
            self.project_id, "game/unity_project/" + entry["animation_metadata_path"]
        )
        metadata = json.loads(staged)
        frames = metadata["animations"][0]["frame_paths"]
        self.assertEqual(len(frames), 2)
        self.assertEqual(
            self.manager.read_project_file(self.project_id, "game/unity_project/" + frames[1]),
            png(Image.new("RGBA", (4, 4), (80, 100, 120, 255))),
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
            ("xp_pickup feedback", "experience reward collected"): "pickup",
            ("level_up feedback", "upgrade choice becomes available"): "level_up",
            ("boss_spawn feedback", "survivor boss enters the arena"): "boss_spawn",
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

    def test_tileset_surface_tile_is_staged_without_changing_the_sheet(self) -> None:
        sheet = Image.new("RGBA", (128, 128), (40, 20, 60, 255))
        for column in range(4):
            sheet.paste((90 + column * 30, 200, 120, 255), (column * 32, 0, column * 32 + 32, 32))
        # Flat sky band above the grass of the surface tile, plus a marker pixel below it.
        sheet.paste((20, 22, 56, 255), (0, 0, 32, 8))
        sheet.paste((255, 255, 255, 255), (0, 8, 4, 12))
        buffer = io.BytesIO()
        sheet.save(buffer, format="PNG")
        sheet_bytes = buffer.getvalue()
        artifact = self.manager.write_bytes(
            self.project_id,
            "image",
            "platformer_tileset.png",
            sheet_bytes,
            producer="test",
            media_type="image/png",
        )
        item = self._image_item("platformer_tileset", True)
        item["generation_spec"] = build_image_generation_spec("맵", "발판과 지형 타일셋")
        image_request = cast(
            AssetGenerationRequest,
            {
                "contract_version": CONTRACT_VERSION,
                "request_id": "images",
                "source_design_id": "design",
                "game_title": "Test",
                "genre": "Platformer",
                "asset_type": "image",
                "image_style": "Pixel Art",
                "mood_style": "Fantasy",
                "viewpoint": "사이드뷰",
                "reference_image": None,
                "output_directory": "generated/images",
                "assets": [item],
            },
        )
        sound_request = cast(
            AssetGenerationRequest,
            {**image_request, "request_id": "sounds", "asset_type": "sound", "assets": []},
        )
        asset = {**self._image_asset("platformer_tileset", artifact), "kind": "tileset"}
        image_draft = cast(
            ImageDraft,
            {
                "contract_version": CONTRACT_VERSION,
                "draft_id": "image-draft",
                "status": "generated",
                "assets": [asset],
                "missing_required_asset_ids": [],
                "notes": ["generator=openai"],
            },
        )
        sound_draft = cast(
            SoundDraft,
            {
                "contract_version": CONTRACT_VERSION,
                "draft_id": "sound-draft",
                "status": "generated",
                "assets": [],
                "missing_required_asset_ids": [],
                "notes": [],
            },
        )

        def validation(ids: list[str]) -> dict[str, object]:
            return {
                "contract_version": CONTRACT_VERSION,
                "status": "passed",
                "checks": [],
                "issues": [],
                "validated_asset_ids": ids,
            }

        result = UnityAssetApplicator(self.manager).apply(
            self.project_id,
            image_request,
            sound_request,
            image_draft,
            sound_draft,
            cast(ImageValidationResult, validation(["platformer_tileset"])),
            cast(SoundValidationResult, validation([])),
        )

        entry = result.manifest["entries"][0]
        project_root = self.manager.resolve_project_path(
            self.project_id, UnityAssetApplicator.UNITY_PROJECT_ROOT
        )
        self.assertEqual(
            entry["surface_tile_path"],
            "Assets/GameTemplate/Generated/AppliedAssets/Images/platformer_tileset_surface.png",
        )
        self.assertEqual((project_root / entry["unity_path"]).read_bytes(), sheet_bytes)
        with Image.open(project_root / entry["surface_tile_path"]) as tile:
            self.assertEqual(tile.size, (32, 32))
            self.assertEqual(tile.getpixel((0, 0))[3], 0)
            self.assertEqual(tile.getpixel((31, 7))[3], 0)
            self.assertEqual(tile.getpixel((0, 8)), (255, 255, 255, 255))
            self.assertEqual(tile.getpixel((20, 20)), (90, 200, 120, 255))
            self.assertTrue(all(tile.getpixel((x, 31))[3] == 255 for x in range(32)))
        # Rows 0-7 are cleared sky, so the solid ground edge starts a quarter down.
        self.assertEqual(entry["surface_top_inset"], 0.25)
        self.assertEqual(
            entry["surface_fill_path"],
            "Assets/GameTemplate/Generated/AppliedAssets/Images/platformer_tileset_fill.png",
        )
        with Image.open(project_root / entry["surface_fill_path"]) as fill:
            self.assertEqual(fill.size, (32, 32))
            self.assertEqual(fill.getpixel((16, 16)), (40, 20, 60, 255))
        self.assertNotIn("scroll_tile_path", entry)

    def test_stage_background_gets_a_mirrored_repeatable_copy(self) -> None:
        image = Image.new("RGBA", (8, 4), (10, 20, 30, 255))
        image.paste((200, 0, 0, 255), (0, 0, 1, 4))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        item = self._image_item("stage_background", False)
        applicator = UnityAssetApplicator(self.manager)

        fields = applicator._stage_scroll_background(
            self.project_id,
            item,
            "Assets/GameTemplate/Generated/AppliedAssets/Images/stage_background.png",
            buffer.getvalue(),
            [],
        )

        path = (
            self.manager.resolve_project_path(
                self.project_id, UnityAssetApplicator.UNITY_PROJECT_ROOT
            )
            / fields["scroll_tile_path"]
        )
        with Image.open(path) as strip:
            self.assertEqual(strip.size, (16, 4))
            # Both seams join identical columns: original left edge meets the mirror's right
            # edge on repeat, and the original right edge meets the mirror's left edge.
            self.assertEqual(strip.getpixel((0, 0)), strip.getpixel((15, 0)))
            self.assertEqual(strip.getpixel((7, 0)), strip.getpixel((8, 0)))
        self.assertEqual(
            applicator._stage_scroll_background(
                self.project_id, self._image_item("platformer_enemy", False), "x.png", b"", []
            ),
            {},
        )

    def test_surface_tile_without_sky_is_kept_opaque(self) -> None:
        grass = Image.new("RGBA", (32, 32), (90, 200, 120, 255))

        result = UnityAssetApplicator._clear_surface_sky(grass)

        self.assertEqual(result.getchannel("A").histogram()[255], 32 * 32)

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

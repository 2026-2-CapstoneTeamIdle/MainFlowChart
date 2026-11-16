from __future__ import annotations

import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from PIL import Image

from game_pipeline.unity_asset_applicator import UnityAssetApplicator

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
_SPEC = importlib.util.spec_from_file_location(
    "reapply_assets", REPOSITORY_ROOT / "tools/reapply_assets.py"
)
reapply_assets = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(reapply_assets)

BACKGROUND_PATH = "Assets/GameTemplate/Generated/AppliedAssets/Images/stage_background.png"


def _edge_colored_background() -> bytes:
    """Every edge has its own color, so any unmatched repeat shows as a seam."""

    image = Image.new("RGBA", (8, 6), (90, 90, 90, 255))
    image.paste((255, 0, 0, 255), (0, 0, 1, 6))  # left
    image.paste((0, 255, 0, 255), (7, 0, 8, 6))  # right
    image.paste((0, 0, 255, 255), (1, 0, 7, 1))  # top
    image.paste((255, 255, 0, 255), (1, 5, 7, 6))  # bottom
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class ScrollBackgroundTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.manager = mock.Mock()
        self.root = Path(self.temporary.name)
        self.manager.resolve_project_path.side_effect = lambda _project, relative: (
            self.root / relative
        )
        self.manager.write_project_file.side_effect = self._write

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _write(self, _project, relative, content, expected_sha256=None):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def _strip(self, genre: str) -> Image.Image:
        fields = UnityAssetApplicator(self.manager)._stage_scroll_background(
            "project",
            {"asset_id": "stage_background", "asset_type": "image"},
            BACKGROUND_PATH,
            _edge_colored_background(),
            [],
            genre,
        )
        return Image.open(
            self.root / UnityAssetApplicator.UNITY_PROJECT_ROOT / fields["scroll_tile_path"]
        ).convert("RGBA")

    @staticmethod
    def _column(image: Image.Image, x: int) -> list[tuple[int, ...]]:
        return [image.getpixel((x, y)) for y in range(image.height)]

    @staticmethod
    def _row(image: Image.Image, y: int) -> list[tuple[int, ...]]:
        return [image.getpixel((x, y)) for x in range(image.width)]

    def test_top_down_background_joins_in_both_directions(self) -> None:
        for genre in ("SurvivorLike", "TowerDefense"):
            with self.subTest(genre=genre):
                strip = self._strip(genre)

                self.assertEqual(strip.size, (16, 12))
                # Repeating the block puts its last column next to its first, and its last
                # row under its first; both pairs must match for an invisible seam.
                self.assertEqual(self._column(strip, 0), self._column(strip, 15))
                self.assertEqual(self._row(strip, 0), self._row(strip, 11))
                # Inner joins between the mirrored quarters also match.
                self.assertEqual(self._column(strip, 7), self._column(strip, 8))
                self.assertEqual(self._row(strip, 5), self._row(strip, 6))

    def test_side_view_background_only_repeats_horizontally(self) -> None:
        strip = self._strip("Platformer")

        self.assertEqual(strip.size, (16, 6))
        self.assertEqual(self._column(strip, 0), self._column(strip, 15))


class ReapplyToolTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.unity_root = Path(self.temporary.name) / "unity_project"
        (self.unity_root / "ProjectSettings").mkdir(parents=True)
        (self.unity_root / "ProjectSettings/ProjectVersion.txt").write_text("m_EditorVersion: x")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_only_binding_scripts_are_refreshed(self) -> None:
        agent_code = "// game logic written by Codex\n"
        for relative in reapply_assets.GAME_LOGIC_SCRIPTS:
            path = self.unity_root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(agent_code, encoding="utf-8")

        report = reapply_assets.sync_binding_scripts(self.unity_root)

        for relative in reapply_assets.GAME_LOGIC_SCRIPTS:
            self.assertEqual((self.unity_root / relative).read_text(encoding="utf-8"), agent_code)
        self.assertEqual(
            sorted(report["kept_game_logic_scripts"]),
            sorted(reapply_assets.GAME_LOGIC_SCRIPTS),
        )
        binder = "Assets/GameTemplate/Editor/GeneratedAssetBinder.cs"
        self.assertIn(binder, report["updated_binding_scripts"])
        self.assertEqual(
            (self.unity_root / binder).read_bytes(),
            (REPOSITORY_ROOT / "unity_template" / binder).read_bytes(),
        )
        self.assertFalse(
            set(reapply_assets.BINDING_SCRIPTS) & set(reapply_assets.GAME_LOGIC_SCRIPTS)
        )

    def test_reapply_uses_the_workflow_image_options(self) -> None:
        cases = (
            (
                {"MAINFLOW_GAME_BUILDER": "codex_cli", "MAINFLOW_APPLY_IMAGE_ASSETS": "on"},
                True,
                False,
            ),
            (
                {"MAINFLOW_GAME_BUILDER": "pipeline", "MAINFLOW_APPLY_IMAGE_ASSETS": "on"},
                False,
                False,
            ),
            (
                {"MAINFLOW_GAME_BUILDER": "pipeline", "MAINFLOW_APPLY_IMAGE_ASSETS": "off"},
                False,
                True,
            ),
        )
        result_file = Path(self.temporary.name) / "result.json"
        result_file.write_text(
            json.dumps(
                {
                    "final_state": {
                        "project_id": "project",
                        **{key: {"key": key} for key in reapply_assets.STATE_KEYS},
                    }
                }
            ),
            encoding="utf-8",
        )
        manager = mock.Mock()
        manager.resolve_project_path.return_value = self.unity_root
        manager.read_json.side_effect = lambda reference: {"status": "generated", **reference}
        application = SimpleNamespace(
            applied_image_asset_ids=[],
            applied_sound_asset_ids=[],
            suppressed_placeholder_image_asset_ids=[],
            manifest={"entries": [], "warnings": []},
        )
        for environment, exclude, skip in cases:
            with (
                self.subTest(environment=environment),
                mock.patch.dict(os.environ, environment),
                mock.patch.object(reapply_assets, "ArtifactManager", return_value=manager),
                mock.patch.object(UnityAssetApplicator, "apply", return_value=application) as apply,
            ):
                report = reapply_assets.reapply(result_file)

                options = apply.call_args.kwargs
                self.assertEqual(options["exclude_placeholder_images"], exclude)
                self.assertEqual(options["skip_image_application"], skip)
                self.assertEqual(report["skip_image_application"], skip)


if __name__ == "__main__":
    unittest.main()

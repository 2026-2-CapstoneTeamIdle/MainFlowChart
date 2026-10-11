from __future__ import annotations

import json
import unittest
from pathlib import Path

from mainflow.contracts import CONTRACT_VERSION


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_ROOT = REPOSITORY_ROOT / "unity_template"


class UnityTemplateTest(unittest.TestCase):
    def test_template_metadata_matches_pipeline_contract(self) -> None:
        metadata = json.loads((TEMPLATE_ROOT / "template.json").read_text(encoding="utf-8"))

        self.assertEqual(metadata["pipeline_contract_version"], CONTRACT_VERSION)
        self.assertEqual(metadata["unity_version"], "6000.0.71f1")
        self.assertEqual(metadata["entry_scene"], "Assets/Scenes/Bootstrap.unity")
        self.assertEqual(
            metadata["bootstrap_modules"],
            ["game_bootstrap", "validation_probe"],
        )

    def test_required_project_and_runtime_files_exist(self) -> None:
        required_paths = [
            "Packages/manifest.json",
            "ProjectSettings/ProjectVersion.txt",
            "Assets/GameTemplate/Runtime/TeamIdle.GameTemplate.Runtime.asmdef",
            "Assets/GameTemplate/Runtime/Core/GameBootstrap.cs",
            "Assets/GameTemplate/Runtime/Core/GameTemplateConfig.cs",
            "Assets/GameTemplate/Runtime/Core/IGameModule.cs",
            "Assets/GameTemplate/Runtime/Core/ValidationProbe.cs",
            "Assets/GameTemplate/Editor/TemplateProjectBuilder.cs",
            "Assets/GameTemplate/Generated/GameTemplateConfig.asset",
            "Assets/Scenes/Bootstrap.unity",
        ]

        for relative_path in required_paths:
            with self.subTest(relative_path=relative_path):
                self.assertTrue((TEMPLATE_ROOT / relative_path).is_file())

    def test_manifest_contains_required_2d_dependencies(self) -> None:
        manifest = json.loads(
            (TEMPLATE_ROOT / "Packages" / "manifest.json").read_text(encoding="utf-8")
        )
        dependencies = manifest["dependencies"]

        self.assertIn("com.unity.2d.sprite", dependencies)
        self.assertIn("com.unity.2d.tilemap", dependencies)
        self.assertIn("com.unity.modules.physics2d", dependencies)

    def test_bootstrap_scene_references_config_and_runtime_scripts(self) -> None:
        scene = (TEMPLATE_ROOT / "Assets" / "Scenes" / "Bootstrap.unity").read_text(
            encoding="utf-8"
        )
        build_settings = (
            TEMPLATE_ROOT / "ProjectSettings" / "EditorBuildSettings.asset"
        ).read_text(encoding="utf-8")

        self.assertIn("d0000000000000000000000000000001", scene)
        self.assertIn("a0000000000000000000000000000001", scene)
        self.assertIn("a0000000000000000000000000000002", scene)
        self.assertIn("Assets/Scenes/Bootstrap.unity", build_settings)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import re
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
            "Assets/GameTemplate/Editor/ModuleComponentCatalog.cs",
            "Assets/GameTemplate/Editor/PrefabSceneAssembler.cs",
            "Assets/GameTemplate/Runtime/Prototype/PrototypeSceneController.cs",
            "Assets/GameTemplate/Generated/GameTemplateConfig.asset",
            "Assets/Scenes/Bootstrap.unity",
        ]

        for relative_path in required_paths:
            with self.subTest(relative_path=relative_path):
                self.assertTrue((TEMPLATE_ROOT / relative_path).is_file())

    def test_builder_runs_prefab_scene_assembler_and_batch_validation(self) -> None:
        builder = (
            TEMPLATE_ROOT / "Assets/GameTemplate/Editor/TemplateProjectBuilder.cs"
        ).read_text(encoding="utf-8")
        assembler = (
            TEMPLATE_ROOT / "Assets/GameTemplate/Editor/PrefabSceneAssembler.cs"
        ).read_text(encoding="utf-8")

        self.assertIn("PrefabSceneAssembler.Assemble", builder)
        self.assertIn("ValidateCurrentSceneForBatch", builder)
        self.assertIn("ModuleComponentCatalog.ValidateForBatch", builder)
        for genre in (
            "Platformer",
            "TowerDefense",
            "CardGame",
            "VisualNovel",
            "RaisingSimulation",
            "SurvivorLike",
        ):
            with self.subTest(genre=genre):
                self.assertIn(f'case "{genre}"', assembler)

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

    def test_genre_module_sources_and_editor_catalog_exist(self) -> None:
        expected_sources = [
            "Assets/GameTemplate/Runtime/Common/GameStateAndRules.cs",
            "Assets/GameTemplate/Runtime/Common/PresentationAndFlow.cs",
            "Assets/GameTemplate/Runtime/Common/CombatAndEconomy.cs",
            "Assets/GameTemplate/Runtime/Platformer/PlatformerModules.cs",
            "Assets/GameTemplate/Runtime/TowerDefense/TowerDefenseModules.cs",
            "Assets/GameTemplate/Runtime/Card/CardGameModules.cs",
            "Assets/GameTemplate/Runtime/VisualNovel/VisualNovelModules.cs",
            "Assets/GameTemplate/Runtime/RaisingSimulation/RaisingSimulationModules.cs",
            "Assets/GameTemplate/Runtime/SurvivorLike/SurvivorLikeModules.cs",
            "Assets/GameTemplate/Editor/ModuleComponentCatalog.cs",
        ]

        for relative_path in expected_sources:
            with self.subTest(relative_path=relative_path):
                self.assertTrue((TEMPLATE_ROOT / relative_path).is_file())

    def test_every_planned_module_has_a_unity_component_mapping(self) -> None:
        catalog = (
            TEMPLATE_ROOT / "Assets/GameTemplate/Editor/ModuleComponentCatalog.cs"
        ).read_text(encoding="utf-8")
        mapped_ids = set(re.findall(r'\["([a-z0-9_]+)"\]\s*=\s*typeof', catalog))

        from game_pipeline.design_catalog import COMMON_MODULES, MECHANIC_TO_MODULE

        planned_ids = set(COMMON_MODULES) | set(MECHANIC_TO_MODULE.values())
        built_in_ids = {"game_bootstrap", "validation_probe"}
        self.assertEqual(planned_ids - built_in_ids, mapped_ids)


if __name__ == "__main__":
    unittest.main()

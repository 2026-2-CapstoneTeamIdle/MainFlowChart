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
            "Assets/GameTemplate/Runtime/Core/IGeneratedFeatureModule.cs",
            "Assets/GameTemplate/Runtime/Core/IGameModule.cs",
            "Assets/GameTemplate/Runtime/Core/ValidationProbe.cs",
            "Assets/GameTemplate/Editor/TemplateProjectBuilder.cs",
            "Assets/GameTemplate/Editor/ModuleComponentCatalog.cs",
            "Assets/GameTemplate/Editor/PrefabSceneAssembler.cs",
            "Assets/GameTemplate/Editor/GameBlueprint.cs",
            "Assets/GameTemplate/Editor/LevelPlan.cs",
            "Assets/GameTemplate/Editor/GameplayPlans.cs",
            "Assets/GameTemplate/Editor/PresentationSceneAssembler.cs",
            "Assets/GameTemplate/Editor/GeneratedAssetBinder.cs",
            "Assets/GameTemplate/Editor/GameImplementationPlan.cs",
            "Assets/GameTemplate/Runtime/Prototype/PrototypeSceneController.cs",
            "Assets/GameTemplate/Runtime/Prototype/PlatformerPrototypeActors.cs",
            "Assets/GameTemplate/Runtime/Prototype/PrototypePlatformerStageController.cs",
            "Assets/GameTemplate/Runtime/Prototype/PrototypePresentationController.cs",
            "Assets/GameTemplate/Runtime/Prototype/PrototypeCheckpoint.cs",
            "Assets/GameTemplate/Runtime/Prototype/PrototypeCollectible.cs",
            "Assets/GameTemplate/Runtime/Prototype/PrototypeGoal.cs",
            "Assets/GameTemplate/Runtime/Prototype/PrototypeHazard.cs",
            "Assets/GameTemplate/Runtime/Prototype/PrototypeExperienceReward.cs",
            "Assets/GameTemplate/Runtime/Prototype/PrototypeTowerEndpoint.cs",
            "Assets/GameTemplate/Runtime/Common/Projectile2D.cs",
            "Assets/GameTemplate/Runtime/Common/ProjectileSystemModule.cs",
            "Assets/GameTemplate/Runtime/SurvivorLike/ChaseAgent2D.cs",
            "Assets/GameTemplate/Runtime/Platformer/CollectibleSystemModule.cs",
            "Assets/GameTemplate/Runtime/Platformer/GoalSystemModule.cs",
            "Assets/GameTemplate/Runtime/Platformer/WallClimbModule.cs",
            "Assets/GameTemplate/Runtime/Platformer/AirDashModule.cs",
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
        asset_binder = (
            TEMPLATE_ROOT / "Assets/GameTemplate/Editor/GeneratedAssetBinder.cs"
        ).read_text(encoding="utf-8")
        runtime_smoke = (
            TEMPLATE_ROOT / "Assets/GameTemplate/Editor/RuntimeSmokeValidator.cs"
        ).read_text(encoding="utf-8")
        level_plan = (TEMPLATE_ROOT / "Assets/GameTemplate/Editor/LevelPlan.cs").read_text(
            encoding="utf-8"
        )
        camera_follow = (
            TEMPLATE_ROOT / "Assets/GameTemplate/Runtime/Prototype/PlatformerPrototypeActors.cs"
        ).read_text(encoding="utf-8")

        self.assertIn("PrefabSceneAssembler.Assemble", builder)
        self.assertIn("GeneratedAssetBinder.ImportAndConfigureAssets", builder)
        self.assertIn("GeneratedAssetBinder.BindSceneAssets", builder)
        self.assertIn("ISpriteEditorDataProvider", asset_binder)
        self.assertIn("ISpriteNameFileIdDataProvider", asset_binder)
        self.assertIn("CreateAndDeleteSprite", asset_binder)
        self.assertNotIn(".meta", asset_binder)
        self.assertNotIn("AudioMixerController", asset_binder)
        self.assertIn('failureDetail = "runtime.exception: " + message', runtime_smoke)
        self.assertNotIn("runtime.exception: inspect Unity log", runtime_smoke)
        self.assertIn("ValidateCurrentSceneForBatch", builder)
        self.assertIn("ModuleComponentCatalog.ValidateForBatch", builder)
        self.assertIn("AttachGeneratedFeatureBinder", assembler)
        self.assertIn("IGeneratedFeatureModule", assembler)
        self.assertIn("GameImplementationPlan.Load()", assembler)
        self.assertIn("GameBlueprint.Load()", assembler)
        self.assertIn("LevelPlan.Load()", assembler)
        self.assertIn("ContentPlan.Load()", assembler)
        self.assertIn("BalancePlan.Load()", assembler)
        self.assertIn("PresentationPlan.Load()", assembler)
        self.assertIn("context.Level", assembler)
        self.assertIn("Zone_", assembler)
        self.assertIn("UNITY_LEVEL_PLAN_OK", assembler)
        self.assertIn("UNITY_GAMEPLAY_TUNING_OK", assembler)
        self.assertIn("UNITY_PRESENTATION_PLAN_OK", assembler)
        self.assertIn("UNITY_VALIDATION_PLAN_STATIC_OK", assembler)
        self.assertIn("ValidationPlan.Load()", assembler)
        self.assertIn("UNITY_VALIDATION_PLAN_OK", runtime_smoke)
        self.assertIn("UNITY_VALIDATION_SCENARIO_OK", runtime_smoke)
        self.assertIn("TickTowerDefenseScenario", runtime_smoke)
        self.assertIn("runtime.tower_spawn", runtime_smoke)
        self.assertIn("TickSurvivorLikeScenario", runtime_smoke)
        self.assertIn("runtime.survivor_chase", runtime_smoke)
        self.assertIn("routeTimeoutSeconds", runtime_smoke)
        self.assertIn("routeDistance / 3f + 10f", runtime_smoke)
        self.assertIn("runtime.route_no_progress", runtime_smoke)
        self.assertIn("enemy.transform.position.x - enemy.Range", runtime_smoke)
        self.assertIn("collectibles[collectibleIndex] == null", runtime_smoke)
        self.assertIn("PresentationSceneAssembler.AssemblePlatformer", assembler)
        self.assertIn("ApplyBlueprintEntities", assembler)
        self.assertIn("PlatformerRoutePosition", assembler)
        self.assertIn("PlatformerLandingWidth", assembler)
        self.assertIn("ResolvePlatformerSpawn", assembler)
        self.assertIn("ResolvePlatformerGoal", assembler)
        self.assertIn("requiredCollectibleScore += rewardAmount", assembler)
        self.assertIn("StageGoal overlaps collectible", assembler)
        self.assertIn("Collectible item target mismatch", assembler)
        self.assertIn("Collectible score target mismatch", assembler)
        self.assertIn("cameraFollow.ConfigureBounds", assembler)
        self.assertIn("Platformer camera bounds do not cover the route", assembler)
        self.assertIn("public void ConfigureBounds", camera_follow)
        self.assertIn("public Transform Target => target", camera_follow)
        self.assertIn("ValidatePlatformerTraversal", assembler)
        self.assertIn("UNITY_PLATFORMER_TRAVERSAL_OK", assembler)
        self.assertIn("PlatformerMinimumLandingWidth", assembler)
        self.assertIn("levelPlan.player_spawn", assembler)
        self.assertIn("string.IsNullOrWhiteSpace(zone.checkpoint.placement_id)", level_plan)
        self.assertIn("foreach (var zone in levelPlan.zones)", assembler)
        self.assertIn("platformPlan.width", assembler)
        self.assertIn("BlueprintNoise", assembler)
        self.assertIn("ConfigureUpgradePool(", assembler)
        self.assertIn("cameraFollow.Bind(player.transform)", assembler)
        self.assertIn("Generated prefab did not preserve", assembler)
        self.assertIn("context.Blueprint", assembler)
        self.assertIn("UNITY_IMPLEMENTATION_PLAN_OK", assembler)
        self.assertIn("UNITY_GAME_BLUEPRINT_OK", assembler)
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

    def test_platformer_buffers_jump_input_before_fixed_update(self) -> None:
        movement = (
            TEMPLATE_ROOT / "Assets/GameTemplate/Runtime/Platformer/PlatformerModules.cs"
        ).read_text(encoding="utf-8")

        self.assertIn("private void Update()", movement)
        self.assertIn("jumpQueuedUntil = Time.time + jumpBufferSeconds", movement)
        self.assertIn("Time.time <= jumpQueuedUntil && IsGrounded()", movement)
        self.assertIn("Physics2D.OverlapCircleAll", movement)
        self.assertIn("overlap.attachedRigidbody == target", movement)
        fixed_update = movement.split("private void FixedUpdate()", maxsplit=1)[1]
        self.assertNotIn("input.ConfirmPressed", fixed_update)

    def test_feature_binding_aliases_match_selected_module_ids(self) -> None:
        validators = (
            "Assets/GameTemplate/Editor/PrefabSceneAssembler.cs",
            "Assets/GameTemplate/Editor/RuntimeSmokeValidator.cs",
        )
        expected_aliases = {
            "item_collect": "item_collection_system",
            "player_stats": "player_stat_display",
        }

        for relative_path in validators:
            source = (TEMPLATE_ROOT / relative_path).read_text(encoding="utf-8")
            for feature_id, module_id in expected_aliases.items():
                with self.subTest(relative_path=relative_path, feature_id=feature_id):
                    self.assertIn(f'["{feature_id}"] = "{module_id}"', source)

    def test_persistent_platformer_behaviours_use_matching_script_filenames(self) -> None:
        platformer_root = TEMPLATE_ROOT / "Assets/GameTemplate/Runtime/Platformer"
        for class_name in (
            "CollectibleSystemModule",
            "GoalSystemModule",
            "WallClimbModule",
            "AirDashModule",
        ):
            with self.subTest(class_name=class_name):
                source_path = platformer_root / f"{class_name}.cs"
                self.assertTrue(source_path.is_file())
                self.assertIn(
                    f"public sealed class {class_name}",
                    source_path.read_text(encoding="utf-8"),
                )

    def test_prefab_behaviours_use_dedicated_script_files(self) -> None:
        expected = {
            "Common/AssetRegistryModule.cs": "AssetRegistryModule",
            "Common/AudioManagerModule.cs": "AudioManagerModule",
            "Common/EconomySystemModule.cs": "EconomySystemModule",
            "Common/EventRuleEngineModule.cs": "EventRuleEngineModule",
            "Common/GameStateStoreModule.cs": "GameStateStoreModule",
            "Common/HealthComponent.cs": "HealthComponent",
            "Common/HealthDamageSystemModule.cs": "HealthDamageSystemModule",
            "Common/InputAdapterModule.cs": "InputAdapterModule",
            "Common/ItemCollectionSystemModule.cs": "ItemCollectionSystemModule",
            "Common/OptionsMenuModule.cs": "OptionsMenuModule",
            "Common/PlayerStatDisplayModule.cs": "PlayerStatDisplayModule",
            "Common/Projectile2D.cs": "Projectile2D",
            "Common/ProjectileSystemModule.cs": "ProjectileSystemModule",
            "Common/SaveSystemModule.cs": "SaveSystemModule",
            "Common/SceneFlowManagerModule.cs": "SceneFlowManagerModule",
            "Common/ScoreSystemModule.cs": "ScoreSystemModule",
            "Common/GameTimerModule.cs": "GameTimerModule",
            "Common/UiRouterModule.cs": "UiRouterModule",
            "SurvivorLike/ChaseAgent2D.cs": "ChaseAgent2D",
            "SurvivorLike/AutoTargetSystemModule.cs": "AutoTargetSystemModule",
            "SurvivorLike/EnemySpawnSystemModule.cs": "EnemySpawnSystemModule",
            "SurvivorLike/ExperienceSystemModule.cs": "ExperienceSystemModule",
            "SurvivorLike/RaritySystemModule.cs": "RaritySystemModule",
            "SurvivorLike/TopDownMovementModule.cs": "TopDownMovementModule",
            "SurvivorLike/UpgradeSelectionSystemModule.cs": "UpgradeSelectionSystemModule",
            "TowerDefense/BaseDefenseSystemModule.cs": "BaseDefenseSystemModule",
            "TowerDefense/PathFollower2D.cs": "PathFollower2D",
            "TowerDefense/TowerTargetingSystemModule.cs": "TowerTargetingSystemModule",
            "TowerDefense/TowerUpgradeSystemModule.cs": "TowerUpgradeSystemModule",
            "TowerDefense/WaveSpawnerModule.cs": "WaveSpawnerModule",
            "Prototype/PrototypeExperienceReward.cs": "PrototypeExperienceReward",
            "Prototype/PrototypeTowerEndpoint.cs": "PrototypeTowerEndpoint",
            "Prototype/PrototypeWingUpgradeApplier.cs": "PrototypeWingUpgradeApplier",
        }
        runtime_root = TEMPLATE_ROOT / "Assets/GameTemplate/Runtime"
        for relative_path, class_name in expected.items():
            with self.subTest(class_name=class_name):
                source_path = runtime_root / relative_path
                self.assertTrue(source_path.is_file())
                self.assertIn(
                    f"public sealed class {class_name}",
                    source_path.read_text(encoding="utf-8"),
                )

    def test_template_meta_guids_are_unique(self) -> None:
        owners: dict[str, Path] = {}
        for meta_path in (TEMPLATE_ROOT / "Assets").rglob("*.meta"):
            match = re.search(
                r"(?m)^guid: ([0-9a-f]{32})$",
                meta_path.read_text(encoding="utf-8"),
            )
            self.assertIsNotNone(match, str(meta_path))
            guid = match.group(1)
            self.assertNotIn(guid, owners, f"{meta_path} duplicates {owners.get(guid)}")
            owners[guid] = meta_path

    def test_manifest_contains_required_2d_dependencies(self) -> None:
        manifest = json.loads(
            (TEMPLATE_ROOT / "Packages" / "manifest.json").read_text(encoding="utf-8")
        )
        dependencies = manifest["dependencies"]

        self.assertIn("com.unity.2d.sprite", dependencies)
        self.assertIn("com.unity.2d.tilemap", dependencies)
        self.assertIn("com.unity.modules.physics2d", dependencies)
        self.assertIn("com.unity.modules.particlesystem", dependencies)
        self.assertIn("com.unity.ugui", dependencies)

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

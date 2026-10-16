using System;
using System.Collections.Generic;
using System.IO;
using TeamIdle.GameTemplate.Card;
using TeamIdle.GameTemplate.Common;
using TeamIdle.GameTemplate.Core;
using TeamIdle.GameTemplate.Platformer;
using TeamIdle.GameTemplate.Prototype;
using TeamIdle.GameTemplate.RaisingSimulation;
using TeamIdle.GameTemplate.SurvivorLike;
using TeamIdle.GameTemplate.TowerDefense;
using TeamIdle.GameTemplate.VisualNovel;
using UnityEditor;
using UnityEngine;

namespace TeamIdle.GameTemplate.Editor
{
    public static class PrefabSceneAssembler
    {
        private const float PlatformerPlayerWidth = 0.8f;
        private const float PlatformerPlayerHeight = 1.2f;
        private const float PlatformerMinimumLandingWidth = 2.4f;
        private const float PlatformerMaximumHorizontalGap = 1.35f;
        private const float PlatformerMaximumStepUp = 1.15f;

        public const string GeneratedPrefabRoot = "Assets/GameTemplate/Generated/Prefabs";
        public const string GeneratedVisualRoot =
            "Assets/GameTemplate/Generated/PlaceholderVisuals";
        public const string ReportPath = "Assets/GameTemplate/Generated/SceneAssemblyReport.json";

        [Serializable]
        private sealed class AssemblyReport
        {
            public string genre = string.Empty;
            public string scene = string.Empty;
            public int sceneObjectCount;
            public List<string> generatedPrefabs = new();
            public List<string> roots = new();
        }

        private sealed class AssemblyContext
        {
            public GameTemplateConfig Config;
            public GameImplementationPlan Plan;
            public GameBlueprint Blueprint;
            public Transform Modules;
            public Transform Environment;
            public Transform Entities;
            public Transform Ui;
            public Camera Camera;
            public AssemblyReport Report;
        }

        public static void Assemble(
            GameTemplateConfig config,
            Transform moduleRoot,
            Camera sceneCamera,
            ValidationProbe validation
        )
        {
            if (config == null || moduleRoot == null || sceneCamera == null)
            {
                throw new ArgumentNullException(
                    "Scene assembly requires config, modules, and camera."
                );
            }

            EnsureAssetFolder(GeneratedPrefabRoot);
            EnsureAssetFolder(GeneratedVisualRoot);
            DeleteGeneratedAssets();

            var generatedRoot = new GameObject("GeneratedGame").transform;
            var environment = CreateRoot("Environment", generatedRoot);
            var entities = CreateRoot("Entities", generatedRoot);
            var ui = CreateRoot("UI", generatedRoot);
            var controller = ui.gameObject.AddComponent<PrototypeSceneController>();
            controller.Configure(config.GameTitle, config.Genre);

            var report = new AssemblyReport
            {
                genre = config.Genre,
                scene = TemplateProjectBuilder.ScenePath,
                roots = new List<string>
                {
                    "GeneratedGame/Environment",
                    "GeneratedGame/Entities",
                    "GeneratedGame/UI",
                },
            };
            var context = new AssemblyContext
            {
                Config = config,
                Plan = GameImplementationPlan.Load(),
                Blueprint = GameBlueprint.Load(),
                Modules = moduleRoot,
                Environment = environment,
                Entities = entities,
                Ui = ui,
                Camera = sceneCamera,
                Report = report,
            };

            context.Blueprint.ApplyContentTo(context.Plan);

            CreateBackground(
                context,
                context.Blueprint.BackgroundColor(new Color(0.055f, 0.065f, 0.09f, 1f))
            );
            switch (config.Genre)
            {
                case "Platformer":
                    AssemblePlatformer(context);
                    break;
                case "TowerDefense":
                    AssembleTowerDefense(context);
                    break;
                case "CardGame":
                    AssembleCardGame(context);
                    break;
                case "VisualNovel":
                    AssembleVisualNovel(context);
                    break;
                case "RaisingSimulation":
                    AssembleRaisingSimulation(context);
                    break;
                case "SurvivorLike":
                    AssembleSurvivorLike(context);
                    break;
                default:
                    validation.Fail("scene.unsupported_genre", config.Genre);
                    break;
            }

            ApplyBlueprintEntities(context);
            AttachGeneratedFeatureBinder(context, generatedRoot.gameObject);
            report.sceneObjectCount = generatedRoot.GetComponentsInChildren<Transform>(true).Length;
            File.WriteAllText(ReportPath, JsonUtility.ToJson(report, true));
            AssetDatabase.ImportAsset(ReportPath, ImportAssetOptions.ForceUpdate);
            validation.Pass(
                "scene.assembled",
                $"{config.Genre}:{report.sceneObjectCount}:{report.generatedPrefabs.Count}"
            );
        }

        public static void ValidateCurrentSceneForBatch(GameTemplateConfig config)
        {
            var generatedRoot = GameObject.Find("GeneratedGame");
            RequireObject(generatedRoot, "GeneratedGame");
            RequireObject(generatedRoot.transform.Find("Environment"), "GeneratedGame/Environment");
            RequireObject(generatedRoot.transform.Find("Entities"), "GeneratedGame/Entities");
            RequireObject(generatedRoot.transform.Find("UI"), "GeneratedGame/UI");
            RequireObject(
                generatedRoot.GetComponentInChildren<PrototypeSceneController>(true),
                "PrototypeSceneController"
            );
            var featureBinder = generatedRoot.GetComponent<GeneratedFeatureBinder>();
            RequireObject(featureBinder, "GeneratedFeatureBinder");
            var implementationPlan = GameImplementationPlan.Load();
            var blueprint = GameBlueprint.Load();
            blueprint.ApplyContentTo(implementationPlan);
            if (implementationPlan.playtest_scenarios.Count < 3)
            {
                throw new InvalidOperationException(
                    "At least three playtest scenarios are required."
                );
            }

            var moduleRoot = GameObject.Find("Modules");
            RequireObject(moduleRoot, "Modules");
            var generatedFeatureCount = 0;
            foreach (var behaviour in moduleRoot.GetComponentsInChildren<MonoBehaviour>(true))
            {
                if (
                    behaviour
                        .GetType()
                        .GetCustomAttributes(typeof(GeneratedGameModuleAttribute), false)
                        .Length == 0
                )
                {
                    continue;
                }

                if (behaviour is not IGeneratedFeatureModule)
                {
                    throw new InvalidOperationException(
                        $"Generated module must implement IGeneratedFeatureModule: {behaviour.GetType().Name}"
                    );
                }

                generatedFeatureCount++;
            }

            var boundFeatureCount = featureBinder.BindNow();
            if (boundFeatureCount != generatedFeatureCount)
            {
                throw new InvalidOperationException(
                    $"Expected {generatedFeatureCount} generated feature bindings but found {boundFeatureCount}."
                );
            }

            var expectedObjects = new Dictionary<string, string[]>
            {
                ["Platformer"] = new[] { "Player", "Ground", "StageGoal", "Collectible_1" },
                ["TowerDefense"] = new[] { "EnemyPath", "Tower", "Base" },
                ["CardGame"] = new[] { "OpponentArea", "PlayerArea", "CardSlot_1" },
                ["VisualNovel"] = new[] { "SceneBackground", "CharacterLeft", "CharacterRight" },
                ["RaisingSimulation"] = new[] { "Room", "Trainee", "ActivityCard_1" },
                ["SurvivorLike"] = new[] { "Player", "ArenaMarker_1" },
            };
            if (!expectedObjects.TryGetValue(config.Genre, out var names))
            {
                throw new InvalidOperationException($"Unknown scene profile: {config.Genre}");
            }

            foreach (var name in names)
            {
                RequireObject(FindChildByName(generatedRoot.transform, name), name);
            }

            if (config.Genre == "Platformer")
            {
                ValidatePlatformerTraversal(generatedRoot.transform);
            }

            if (!File.Exists(ReportPath))
            {
                throw new InvalidOperationException(
                    $"Scene assembly report is missing: {ReportPath}"
                );
            }

            Debug.Log($"UNITY_GENERATED_FEATURE_BINDINGS_OK:{boundFeatureCount}");
            Debug.Log(
                $"UNITY_IMPLEMENTATION_PLAN_OK:{implementationPlan.complexity_tier}:"
                    + implementationPlan.playtest_scenarios.Count
            );
            Debug.Log($"UNITY_SCENE_ASSEMBLY_OK:{config.Genre}:{names.Length}");
            Debug.Log(
                $"UNITY_GAME_BLUEPRINT_OK:{blueprint.blueprint_id}:{blueprint.entities.Count}"
            );
        }

        private static void ApplyBlueprintEntities(AssemblyContext context)
        {
            foreach (var entity in context.Blueprint.entities)
            {
                if (string.IsNullOrWhiteSpace(entity.entity_id))
                {
                    continue;
                }

                if (entity.archetype == "player_anchor")
                {
                    var player = FindChildByName(context.Entities, "Player");
                    if (player != null && context.Config.Genre != "Platformer")
                    {
                        player.position = new Vector2(entity.position_x, entity.position_y);
                    }
                    continue;
                }

                var color = ColorUtility.TryParseHtmlString(entity.color_hex, out var parsedColor)
                    ? parsedColor
                    : Color.white;
                var parent =
                    entity.archetype == "landmark" ? context.Environment : context.Entities;
                var marker = CreateSpriteObject(
                    $"Blueprint_{entity.entity_id}",
                    parent,
                    new Vector2(entity.position_x, entity.position_y),
                    new Vector2(Mathf.Max(0.1f, entity.scale_x), Mathf.Max(0.1f, entity.scale_y)),
                    color,
                    $"blueprint-{entity.entity_id}",
                    entity.archetype == "landmark" ? -5 : 1
                );
                marker.name = $"Blueprint_{entity.display_name}";
            }

            context.Camera.orthographicSize = Mathf.Max(
                context.Camera.orthographicSize,
                context.Blueprint.scene_height * 0.34f
            );
        }

        private static void AttachGeneratedFeatureBinder(
            AssemblyContext context,
            GameObject generatedRoot
        )
        {
            var player = FindChildByName(context.Entities, "Player");
            var binder = generatedRoot.AddComponent<GeneratedFeatureBinder>();
            binder.Configure(
                player == null ? null : player.gameObject,
                context.Modules,
                context.Environment,
                context.Entities,
                context.Ui
            );
        }

        private static void AssemblePlatformer(AssemblyContext context)
        {
            context.Camera.orthographicSize = 5.5f;
            context.Camera.transform.position = new Vector3(0f, 0f, -10f);
            var stageWidth = Mathf.Max(30f, context.Blueprint.scene_width);
            var playerSpawn = new Vector2(-stageWidth * 0.5f + 2.5f, -2.75f);
            var player = CreateSpriteObject(
                "Player",
                context.Entities,
                playerSpawn,
                new Vector2(PlatformerPlayerWidth, PlatformerPlayerHeight),
                new Color(0.25f, 0.75f, 1f),
                "platformer-player"
            );
            player.tag = "Player";
            var playerBody = player.AddComponent<Rigidbody2D>();
            playerBody.freezeRotation = true;
            playerBody.gravityScale = 3f;
            player.AddComponent<BoxCollider2D>();
            player.AddComponent<HealthComponent>();
            var stageController =
                context.Ui.gameObject.AddComponent<PrototypePlatformerStageController>();
            stageController.Bind(player.transform);
            context.Camera.gameObject.AddComponent<PrototypeCameraFollow>().Bind(player.transform);
            var groundCheck = new GameObject("GroundCheck").transform;
            groundCheck.SetParent(player.transform, false);
            groundCheck.localPosition = new Vector3(0f, -PlatformerPlayerHeight * 0.55f, 0f);

            CreatePlatform(context, "Ground", new Vector2(0f, -4f), new Vector2(stageWidth, 1f));
            var platformCount = context.Plan.Count("platform", 10);
            for (var index = 0; index < platformCount; index++)
            {
                var position = PlatformerRoutePosition(context, index, platformCount);
                CreatePlatform(
                    context,
                    $"Platform_{index + 1}",
                    position,
                    new Vector2(PlatformerLandingWidth(context, platformCount, index), 0.45f)
                );
            }

            var movement = GetModule<PlatformerMovementModule>(context);
            movement?.Bind(playerBody, groundCheck);
            GetModule<WallClimbModule>(context)?.Bind(playerBody);
            GetModule<AirDashModule>(context)?.Bind(playerBody, groundCheck);
            var collectibleCount = context.Plan.Count("collectible", 8);
            SetInt(GetModule<CollectibleSystemModule>(context), "requiredCount", collectibleCount);

            for (var index = 0; index < collectibleCount; index++)
            {
                var platformPosition = PlatformerRoutePosition(
                    context,
                    index % platformCount,
                    platformCount
                );
                var collectible = CreateSpriteObject(
                    $"Collectible_{index + 1}",
                    context.Entities,
                    platformPosition
                        + new Vector2(0f, 0.75f + BlueprintNoise(context, index + 40, 0.2f)),
                    Vector2.one * 0.45f,
                    new Color(1f, 0.82f, 0.2f),
                    "collectible"
                );
                var collider = collectible.AddComponent<CircleCollider2D>();
                collider.isTrigger = true;
                collectible.AddComponent<PrototypeCollectible>();
            }

            for (var index = 0; index < context.Plan.Count("hazard", 5); index++)
            {
                var hazardCount = context.Plan.Count("hazard", 5);
                var progress = (index + 1f) / (hazardCount + 1f);
                var hazard = CreateSpriteObject(
                    $"Hazard_{index + 1}",
                    context.Entities,
                    new Vector2(
                        Mathf.Lerp(
                            playerSpawn.x + PlatformerPlayerWidth * 4f,
                            stageWidth * 0.5f - 4.5f,
                            progress
                        ),
                        -3.3f
                    ),
                    new Vector2(0.9f, 0.35f),
                    new Color(1f, 0.2f, 0.25f),
                    "hazard"
                );
                var collider = hazard.AddComponent<BoxCollider2D>();
                collider.isTrigger = true;
                hazard.AddComponent<PrototypeHazard>();
            }

            for (var index = 0; index < context.Plan.Count("checkpoint", 2); index++)
            {
                var progress = (index + 1f) / (context.Plan.Count("checkpoint", 2) + 1f);
                var checkpoint = CreateSpriteObject(
                    $"Checkpoint_{index + 1}",
                    context.Entities,
                    new Vector2(
                        Mathf.Lerp(-stageWidth * 0.25f, stageWidth * 0.3f, progress),
                        -2.8f
                    ),
                    new Vector2(0.45f, 1.8f),
                    new Color(0.25f, 0.9f, 0.95f),
                    "checkpoint"
                );
                var collider = checkpoint.AddComponent<BoxCollider2D>();
                collider.isTrigger = true;
                checkpoint.AddComponent<PrototypeCheckpoint>().Configure(index + 1);
            }

            for (var index = 0; index < context.Plan.Count("enemy", 3); index++)
            {
                var platformPosition = PlatformerRoutePosition(
                    context,
                    (index + 2) % platformCount,
                    platformCount
                );
                var enemy = CreateSpriteObject(
                    $"PatrolEnemy_{index + 1}",
                    context.Entities,
                    platformPosition + new Vector2(0.25f, 0.65f),
                    new Vector2(0.8f, 0.8f),
                    new Color(0.95f, 0.35f, 0.4f),
                    "platformer-enemy"
                );
                enemy.AddComponent<BoxCollider2D>();
                var body = enemy.AddComponent<Rigidbody2D>();
                body.bodyType = RigidbodyType2D.Kinematic;
                enemy.AddComponent<PrototypePatrolEnemy>();
            }

            var goal = CreateSpriteObject(
                "StageGoal",
                context.Entities,
                new Vector2(stageWidth * 0.5f - 2.25f, -2.5f),
                new Vector2(0.8f, 2f),
                new Color(0.2f, 1f, 0.45f),
                "goal"
            );
            var goalCollider = goal.AddComponent<BoxCollider2D>();
            goalCollider.isTrigger = true;
            goal.AddComponent<PrototypeGoal>();
        }

        private static void AssembleTowerDefense(AssemblyContext context)
        {
            context.Camera.orthographicSize = 6f;
            var pathRoot = CreateRoot("EnemyPath", context.Environment);
            var waypointPositions = new[]
            {
                new Vector2(-8f, 2.5f),
                new Vector2(-3f, 2.5f),
                new Vector2(-3f, -2f),
                new Vector2(2.5f, -2f),
                new Vector2(2.5f, 2f),
                new Vector2(8f, 2f),
            };
            for (var index = 1; index < waypointPositions.Length - 1; index++)
            {
                waypointPositions[index] += new Vector2(
                    BlueprintNoise(context, index + 100, 0.8f),
                    BlueprintNoise(context, index + 120, 0.65f)
                );
            }
            var waypoints = new List<Transform>();
            for (var index = 0; index < waypointPositions.Length; index++)
            {
                var marker = CreateSpriteObject(
                    $"Waypoint_{index + 1}",
                    pathRoot,
                    waypointPositions[index],
                    Vector2.one * 0.35f,
                    new Color(0.5f, 0.55f, 0.65f),
                    "path-marker"
                );
                waypoints.Add(marker.transform);
            }

            var enemyPrefab = CreateTowerEnemyPrefab(context);
            var projectilePrefab = CreateProjectilePrefab(
                context,
                "TowerProjectile",
                new Color(1f, 0.75f, 0.15f)
            );
            var waveSpawner = GetModule<WaveSpawnerModule>(context);
            SetObject(waveSpawner, "enemyPrefab", enemyPrefab);
            SetObject(waveSpawner, "spawnPoint", waypoints[0]);
            SetObjectList(waveSpawner, "waypoints", waypoints);

            var towerModule = GetModule<TowerTargetingSystemModule>(context);
            SetObject(towerModule, "projectilePrefab", projectilePrefab);
            SetInt(towerModule, "enemyMask", 1 << 8);
            var towerVisual = CreateSpriteObject(
                "Tower",
                context.Entities,
                new Vector2(BlueprintNoise(context, 140, 1.2f), BlueprintNoise(context, 141, 0.8f)),
                new Vector2(1.2f, 1.6f),
                new Color(0.3f, 0.8f, 1f),
                "tower"
            );
            if (towerModule != null)
            {
                towerModule.transform.position = towerVisual.transform.position;
            }

            CreateSpriteObject(
                "Base",
                context.Entities,
                waypointPositions[^1],
                new Vector2(1.4f, 2f),
                new Color(0.2f, 1f, 0.5f),
                "base"
            );
        }

        private static void AssembleCardGame(AssemblyContext context)
        {
            context.Camera.orthographicSize = 6f;
            CreateSpriteObject(
                "OpponentArea",
                context.Environment,
                new Vector2(2f, 2.6f),
                new Vector2(9f, 2.2f),
                new Color(0.25f, 0.18f, 0.32f),
                "card-opponent-area"
            );
            CreateSpriteObject(
                "PlayerArea",
                context.Environment,
                new Vector2(2f, -2.3f),
                new Vector2(9f, 2.5f),
                new Color(0.12f, 0.28f, 0.36f),
                "card-player-area"
            );
            for (var index = 0; index < context.Plan.Count("starting_hand_slot", 5); index++)
            {
                CreateSpriteObject(
                    $"CardSlot_{index + 1}",
                    context.Entities,
                    new Vector2(-2f + index * 1.65f, -2.3f),
                    new Vector2(1.2f, 1.8f),
                    new Color(0.82f, 0.78f, 0.62f),
                    "card"
                );
            }

            var deck = GetModule<DeckSystemModule>(context);
            var serialized = new SerializedObject(deck);
            var cards = serialized.FindProperty("startingDeck");
            cards.arraySize = context.Plan.Count("card", 20);
            for (var index = 0; index < cards.arraySize; index++)
            {
                var card = cards.GetArrayElementAtIndex(index);
                card.FindPropertyRelative("cardId").stringValue = $"prototype-card-{index + 1}";
                card.FindPropertyRelative("displayName").stringValue =
                    $"Prototype Card {index + 1}";
                card.FindPropertyRelative("cost").intValue = index % 3 + 1;
                card.FindPropertyRelative("power").intValue = 4 + index * 2;
                card.FindPropertyRelative("description").stringValue =
                    "Generated placeholder card effect.";
            }

            serialized.ApplyModifiedPropertiesWithoutUndo();
        }

        private static void AssembleVisualNovel(AssemblyContext context)
        {
            context.Camera.orthographicSize = 5f;
            CreateSpriteObject(
                "SceneBackground",
                context.Environment,
                new Vector2(2f, 0f),
                new Vector2(12f, 9f),
                new Color(0.2f, 0.24f, 0.38f),
                "novel-background"
            );
            CreateSpriteObject(
                "CharacterLeft",
                context.Entities,
                new Vector2(-0.5f, -0.5f),
                new Vector2(2.2f, 5f),
                new Color(0.75f, 0.42f, 0.68f),
                "novel-character-left"
            );
            CreateSpriteObject(
                "CharacterRight",
                context.Entities,
                new Vector2(4.5f, -0.5f),
                new Vector2(2.2f, 5f),
                new Color(0.38f, 0.7f, 0.85f),
                "novel-character-right"
            );
            var dialogue = GetModule<DialogueRunnerModule>(context);
            var serialized = new SerializedObject(dialogue);
            var lines = serialized.FindProperty("lines");
            lines.arraySize = context.Plan.Count("dialogue_line", 40);
            SetDialogueLine(
                lines.GetArrayElementAtIndex(0),
                "intro-1",
                "Guide",
                context.Blueprint.summary
            );
            SetDialogueLine(
                lines.GetArrayElementAtIndex(1),
                "intro-2",
                "Hero",
                context.Blueprint.core_loop[0]
            );
            SetDialogueLine(
                lines.GetArrayElementAtIndex(2),
                "intro-3",
                "Guide",
                context.Blueprint.core_loop[1]
            );
            for (var index = 3; index < lines.arraySize; index++)
            {
                SetDialogueLine(
                    lines.GetArrayElementAtIndex(index),
                    $"generated-{index + 1}",
                    index % 2 == 0 ? "Hero" : "Guide",
                    $"{context.Blueprint.core_loop[index % context.Blueprint.core_loop.Count]}: "
                        + $"generated story beat {index + 1}."
                );
            }
            serialized.ApplyModifiedPropertiesWithoutUndo();
        }

        private static void AssembleRaisingSimulation(AssemblyContext context)
        {
            context.Camera.orthographicSize = 5.5f;
            CreateSpriteObject(
                "Room",
                context.Environment,
                new Vector2(2f, 0f),
                new Vector2(12f, 9f),
                new Color(0.3f, 0.25f, 0.2f),
                "raising-room"
            );
            CreateSpriteObject(
                "Trainee",
                context.Entities,
                new Vector2(3.5f, -0.5f),
                new Vector2(2.5f, 5f),
                new Color(0.85f, 0.55f, 0.42f),
                "raising-character"
            );
            for (var index = 0; index < context.Plan.Count("activity", 8); index++)
            {
                CreateSpriteObject(
                    $"ActivityCard_{index + 1}",
                    context.Entities,
                    new Vector2(-3.5f + (index % 4) * 1.8f, -3f + (index / 4) * 1.35f),
                    new Vector2(1.4f, 1.2f),
                    new Color(0.75f, 0.68f - index * 0.08f, 0.35f + index * 0.12f),
                    "activity-card"
                );
            }

            var stats = GetModule<StatSystemModule>(context);
            var serialized = new SerializedObject(stats);
            var initialStats = serialized.FindProperty("initialStats");
            var values = new[] { ("knowledge", 10), ("fitness", 10), ("fatigue", 0) };
            initialStats.arraySize = values.Length;
            for (var index = 0; index < values.Length; index++)
            {
                var item = initialStats.GetArrayElementAtIndex(index);
                item.FindPropertyRelative("statId").stringValue = values[index].Item1;
                item.FindPropertyRelative("value").intValue = values[index].Item2;
                item.FindPropertyRelative("minimum").intValue = 0;
                item.FindPropertyRelative("maximum").intValue = 100;
            }

            serialized.ApplyModifiedPropertiesWithoutUndo();
        }

        private static void AssembleSurvivorLike(AssemblyContext context)
        {
            context.Camera.orthographicSize = 6f;
            var player = CreateSpriteObject(
                "Player",
                context.Entities,
                Vector2.zero,
                new Vector2(1f, 1.2f),
                new Color(0.25f, 0.75f, 1f),
                "survivor-player"
            );
            player.tag = "Player";
            var body = player.AddComponent<Rigidbody2D>();
            body.gravityScale = 0f;
            body.freezeRotation = true;
            player.AddComponent<CircleCollider2D>();
            player.AddComponent<HealthComponent>();
            player.AddComponent<PrototypeWingUpgradeApplier>();
            GetModule<TopDownMovementModule>(context)?.Bind(body);

            CreateSpriteObject(
                "LeftWing",
                player.transform,
                new Vector2(-0.75f, 0f),
                new Vector2(0.8f, 0.35f),
                new Color(0.85f, 0.9f, 1f),
                "wing"
            );
            CreateSpriteObject(
                "RightWing",
                player.transform,
                new Vector2(0.75f, 0f),
                new Vector2(0.8f, 0.35f),
                new Color(0.85f, 0.9f, 1f),
                "wing"
            );

            var enemyPrefab = CreateSurvivorEnemyPrefab(context);
            var projectilePrefab = CreateProjectilePrefab(
                context,
                "FeatherProjectile",
                new Color(0.95f, 0.95f, 1f)
            );
            var spawner = GetModule<EnemySpawnSystemModule>(context);
            SetObject(spawner, "enemyPrefab", enemyPrefab);
            SetObject(spawner, "target", player.transform);
            SetFloat(spawner, "spawnInterval", 1.25f);
            SetInt(spawner, "maximumAlive", 24);

            var autoTarget = GetModule<AutoTargetSystemModule>(context);
            SetObject(autoTarget, "origin", player.transform);
            SetObject(autoTarget, "projectilePrefab", projectilePrefab);
            SetInt(autoTarget, "enemyMask", 1 << 8);
            ConfigureUpgradePool(
                GetModule<UpgradeSelectionSystemModule>(context),
                context.Blueprint
            );

            var arenaMarkerCount = context.Plan.Count("arena_marker", 20);
            for (var index = 0; index < arenaMarkerCount; index++)
            {
                var angle = index / (float)arenaMarkerCount * Mathf.PI * 2f;
                CreateSpriteObject(
                    $"ArenaMarker_{index + 1}",
                    context.Environment,
                    new Vector2(Mathf.Cos(angle), Mathf.Sin(angle))
                        * (
                            Mathf.Min(context.Blueprint.scene_width, context.Blueprint.scene_height)
                                * 0.42f
                            + BlueprintNoise(context, index + 180, 0.8f)
                        ),
                    Vector2.one * 0.2f,
                    new Color(0.3f, 0.35f, 0.45f),
                    "arena-marker"
                );
            }
        }

        private static ChaseAgent2D CreateSurvivorEnemyPrefab(AssemblyContext context)
        {
            var source = CreateSpriteObject(
                "SurvivorEnemy",
                null,
                Vector2.zero,
                Vector2.one,
                new Color(1f, 0.3f, 0.35f),
                "survivor-enemy"
            );
            source.layer = 8;
            source.AddComponent<CircleCollider2D>();
            var health = source.AddComponent<HealthComponent>();
            SetBool(health, "destroyOnDeath", true);
            source.AddComponent<PrototypeExperienceReward>();
            source.AddComponent<ChaseAgent2D>();
            var path = $"{GeneratedPrefabRoot}/SurvivorEnemy.prefab";
            var prefab = SavePrefab<ChaseAgent2D>(source, path, context);
            UnityEngine.Object.DestroyImmediate(source);
            return prefab;
        }

        private static PathFollower2D CreateTowerEnemyPrefab(AssemblyContext context)
        {
            var source = CreateSpriteObject(
                "TowerEnemy",
                null,
                Vector2.zero,
                Vector2.one,
                new Color(1f, 0.38f, 0.3f),
                "tower-enemy"
            );
            source.layer = 8;
            source.AddComponent<CircleCollider2D>();
            var health = source.AddComponent<HealthComponent>();
            SetBool(health, "destroyOnDeath", true);
            source.AddComponent<PrototypeTowerEndpoint>();
            source.AddComponent<PathFollower2D>();
            var path = $"{GeneratedPrefabRoot}/TowerEnemy.prefab";
            var prefab = SavePrefab<PathFollower2D>(source, path, context);
            UnityEngine.Object.DestroyImmediate(source);
            return prefab;
        }

        private static Projectile2D CreateProjectilePrefab(
            AssemblyContext context,
            string name,
            Color color
        )
        {
            var source = CreateSpriteObject(
                name,
                null,
                Vector2.zero,
                new Vector2(0.45f, 0.18f),
                color,
                "projectile"
            );
            var collider = source.AddComponent<CircleCollider2D>();
            collider.isTrigger = true;
            var body = source.AddComponent<Rigidbody2D>();
            body.gravityScale = 0f;
            body.bodyType = RigidbodyType2D.Kinematic;
            source.AddComponent<Projectile2D>();
            var path = $"{GeneratedPrefabRoot}/{name}.prefab";
            var prefab = SavePrefab<Projectile2D>(source, path, context);
            UnityEngine.Object.DestroyImmediate(source);
            return prefab;
        }

        private static T SavePrefab<T>(GameObject source, string path, AssemblyContext context)
            where T : Component
        {
            var saved = PrefabUtility.SaveAsPrefabAsset(source, path);
            if (saved == null)
            {
                throw new InvalidOperationException($"Failed to save generated prefab: {path}");
            }

            context.Report.generatedPrefabs.Add(path);
            return saved.GetComponent<T>();
        }

        private static void ConfigureUpgradePool(
            UpgradeSelectionSystemModule upgrades,
            GameBlueprint blueprint
        )
        {
            if (upgrades == null)
            {
                return;
            }

            var entries = new List<(string Id, string Name, string Description)>();
            foreach (var option in blueprint.progression_options)
            {
                entries.Add((option.option_id, option.display_name, option.description));
            }
            if (entries.Count == 0)
            {
                entries.Add(("wing-power", "Stronger Wings", "Increase feather attack power."));
                entries.Add(("wing-speed", "Swift Wings", "Increase movement speed."));
                entries.Add(("attack-speed", "Rapid Feathers", "Increase attack speed."));
                entries.Add(("feather-count", "Many Feathers", "Fire one additional feather."));
            }
            var serialized = new SerializedObject(upgrades);
            var pool = serialized.FindProperty("upgradePool");
            pool.arraySize = entries.Count;
            for (var index = 0; index < entries.Count; index++)
            {
                var entry = pool.GetArrayElementAtIndex(index);
                entry.FindPropertyRelative("upgradeId").stringValue = entries[index].Item1;
                entry.FindPropertyRelative("displayName").stringValue = entries[index].Item2;
                entry.FindPropertyRelative("description").stringValue = entries[index].Item3;
            }

            serialized.ApplyModifiedPropertiesWithoutUndo();
        }

        private static Vector2 PlatformerRoutePosition(
            AssemblyContext context,
            int index,
            int platformCount
        )
        {
            var stageWidth = Mathf.Max(30f, context.Blueprint.scene_width);
            var spacing = (stageWidth - 9.5f) / Mathf.Max(1, platformCount - 1);
            var routeLevels = new[] { -2.15f, -1.05f, 0.05f, -1.05f, -2.15f };
            return new Vector2(
                -stageWidth * 0.5f + 5f + spacing * index,
                routeLevels[index % routeLevels.Length] + BlueprintNoise(context, index + 20, 0.04f)
            );
        }

        private static float PlatformerLandingWidth(
            AssemblyContext context,
            int platformCount,
            int index
        )
        {
            var stageWidth = Mathf.Max(30f, context.Blueprint.scene_width);
            var spacing = (stageWidth - 9.5f) / Mathf.Max(1, platformCount - 1);
            var variation = BlueprintNoise(context, index, 0.16f);
            return Mathf.Max(
                PlatformerMinimumLandingWidth,
                spacing - PlatformerMaximumHorizontalGap + variation
            );
        }

        private static void ValidatePlatformerTraversal(Transform generatedRoot)
        {
            Physics2D.SyncTransforms();
            var player = FindChildByName(generatedRoot, "Player");
            var playerCollider = player == null ? null : player.GetComponent<BoxCollider2D>();
            RequireObject(playerCollider, "Player BoxCollider2D");

            foreach (var hazard in generatedRoot.GetComponentsInChildren<PrototypeHazard>(true))
            {
                var hazardCollider = hazard.GetComponent<Collider2D>();
                if (
                    hazardCollider != null
                    && hazardCollider.bounds.Intersects(playerCollider.bounds)
                )
                {
                    throw new InvalidOperationException(
                        $"Platformer spawn overlaps hazard: {hazard.name}"
                    );
                }
            }

            foreach (var collider in generatedRoot.GetComponentsInChildren<Collider2D>(true))
            {
                if (
                    collider == playerCollider
                    || collider.isTrigger
                    || !collider.bounds.Intersects(playerCollider.bounds)
                )
                {
                    continue;
                }

                throw new InvalidOperationException(
                    $"Platformer spawn overlaps solid collider: {collider.name}"
                );
            }

            var platforms = new List<BoxCollider2D>();
            foreach (var collider in generatedRoot.GetComponentsInChildren<BoxCollider2D>(true))
            {
                if (collider.name.StartsWith("Platform_", StringComparison.Ordinal))
                {
                    platforms.Add(collider);
                }
            }

            platforms.Sort((left, right) => left.bounds.center.x.CompareTo(right.bounds.center.x));
            if (platforms.Count < 2)
            {
                throw new InvalidOperationException(
                    "Platformer route needs at least two platforms."
                );
            }

            var minimumLandingWidth = playerCollider.bounds.size.x * 2.5f;
            for (var index = 0; index < platforms.Count; index++)
            {
                var current = platforms[index].bounds;
                if (current.size.x < minimumLandingWidth)
                {
                    throw new InvalidOperationException(
                        $"Platform_{index + 1} is narrower than the player-safe landing width."
                    );
                }

                if (index == 0)
                {
                    continue;
                }

                var previous = platforms[index - 1].bounds;
                var horizontalGap = current.min.x - previous.max.x;
                var stepUp = current.max.y - previous.max.y;
                if (horizontalGap > PlatformerMaximumHorizontalGap)
                {
                    throw new InvalidOperationException(
                        $"Platformer route gap {index} is too wide: {horizontalGap:F2}."
                    );
                }

                if (stepUp > PlatformerMaximumStepUp)
                {
                    throw new InvalidOperationException(
                        $"Platformer route step {index} is too high: {stepUp:F2}."
                    );
                }
            }

            Debug.Log(
                $"UNITY_PLATFORMER_TRAVERSAL_OK:{platforms.Count}:"
                    + $"{playerCollider.bounds.size.x:F2}x{playerCollider.bounds.size.y:F2}"
            );
        }

        private static float BlueprintNoise(AssemblyContext context, int sample, float amplitude)
        {
            unchecked
            {
                uint hash = 2166136261;
                foreach (var character in context.Blueprint.blueprint_id)
                {
                    hash = (hash ^ character) * 16777619;
                }
                hash = (hash ^ (uint)sample) * 16777619;
                var normalized = (hash & 0xFFFF) / 65535f;
                return (normalized * 2f - 1f) * amplitude;
            }
        }

        private static void SetDialogueLine(
            SerializedProperty property,
            string id,
            string speaker,
            string text
        )
        {
            property.FindPropertyRelative("lineId").stringValue = id;
            property.FindPropertyRelative("speaker").stringValue = speaker;
            property.FindPropertyRelative("text").stringValue = text;
        }

        private static void CreateBackground(AssemblyContext context, Color color)
        {
            CreateSpriteObject(
                "Background",
                context.Environment,
                Vector2.zero,
                new Vector2(
                    Mathf.Max(30f, context.Blueprint.scene_width),
                    Mathf.Max(20f, context.Blueprint.scene_height)
                ),
                color,
                "background",
                -100
            );
        }

        private static void CreatePlatform(
            AssemblyContext context,
            string name,
            Vector2 position,
            Vector2 size
        )
        {
            var platform = CreateSpriteObject(
                name,
                context.Environment,
                position,
                size,
                new Color(0.28f, 0.34f, 0.42f),
                "platform"
            );
            platform.AddComponent<BoxCollider2D>();
        }

        private static GameObject CreateSpriteObject(
            string name,
            Transform parent,
            Vector2 position,
            Vector2 scale,
            Color color,
            string spriteId,
            int sortingOrder = 0
        )
        {
            var gameObject = new GameObject(name);
            if (parent != null)
            {
                gameObject.transform.SetParent(parent, false);
            }

            gameObject.transform.position = position;
            gameObject.transform.localScale = new Vector3(scale.x, scale.y, 1f);
            var renderer = gameObject.AddComponent<SpriteRenderer>();
            renderer.sprite = GetOrCreateSprite(spriteId, color);
            renderer.sortingOrder = sortingOrder;
            return gameObject;
        }

        private static Sprite GetOrCreateSprite(string spriteId, Color color)
        {
            var safeId = spriteId.Replace(' ', '-').ToLowerInvariant();
            var assetPath = $"{GeneratedVisualRoot}/{safeId}.png";
            if (!File.Exists(assetPath))
            {
                var texture = new Texture2D(16, 16, TextureFormat.RGBA32, false);
                var pixels = new Color[16 * 16];
                for (var index = 0; index < pixels.Length; index++)
                {
                    pixels[index] = color;
                }

                texture.SetPixels(pixels);
                texture.Apply();
                File.WriteAllBytes(assetPath, texture.EncodeToPNG());
                UnityEngine.Object.DestroyImmediate(texture);
                AssetDatabase.ImportAsset(assetPath, ImportAssetOptions.ForceSynchronousImport);
                var importer = (TextureImporter)AssetImporter.GetAtPath(assetPath);
                importer.textureType = TextureImporterType.Sprite;
                importer.spritePixelsPerUnit = 16f;
                importer.filterMode = FilterMode.Point;
                importer.mipmapEnabled = false;
                importer.alphaIsTransparency = true;
                importer.SaveAndReimport();
            }

            return AssetDatabase.LoadAssetAtPath<Sprite>(assetPath);
        }

        private static Transform CreateRoot(string name, Transform parent)
        {
            var root = new GameObject(name).transform;
            root.SetParent(parent, false);
            return root;
        }

        private static T GetModule<T>(AssemblyContext context)
            where T : Component
        {
            return context.Modules.GetComponent<T>();
        }

        private static void SetObject(
            UnityEngine.Object target,
            string propertyName,
            UnityEngine.Object value
        )
        {
            if (target == null)
            {
                return;
            }

            var serialized = new SerializedObject(target);
            serialized.FindProperty(propertyName).objectReferenceValue = value;
            serialized.ApplyModifiedPropertiesWithoutUndo();
        }

        private static void SetObjectList<T>(
            UnityEngine.Object target,
            string propertyName,
            IReadOnlyList<T> values
        )
            where T : UnityEngine.Object
        {
            if (target == null)
            {
                return;
            }

            var serialized = new SerializedObject(target);
            var property = serialized.FindProperty(propertyName);
            property.arraySize = values.Count;
            for (var index = 0; index < values.Count; index++)
            {
                property.GetArrayElementAtIndex(index).objectReferenceValue = values[index];
            }

            serialized.ApplyModifiedPropertiesWithoutUndo();
        }

        private static void SetInt(UnityEngine.Object target, string propertyName, int value)
        {
            SetValue(target, propertyName, property => property.intValue = value);
        }

        private static void SetFloat(UnityEngine.Object target, string propertyName, float value)
        {
            SetValue(target, propertyName, property => property.floatValue = value);
        }

        private static void SetBool(UnityEngine.Object target, string propertyName, bool value)
        {
            SetValue(target, propertyName, property => property.boolValue = value);
        }

        private static void SetValue(
            UnityEngine.Object target,
            string propertyName,
            Action<SerializedProperty> setter
        )
        {
            if (target == null)
            {
                return;
            }

            var serialized = new SerializedObject(target);
            setter(serialized.FindProperty(propertyName));
            serialized.ApplyModifiedPropertiesWithoutUndo();
        }

        private static void DeleteGeneratedAssets()
        {
            foreach (
                var path in AssetDatabase.FindAssets(string.Empty, new[] { GeneratedPrefabRoot })
            )
            {
                AssetDatabase.DeleteAsset(AssetDatabase.GUIDToAssetPath(path));
            }

            foreach (
                var path in AssetDatabase.FindAssets(string.Empty, new[] { GeneratedVisualRoot })
            )
            {
                AssetDatabase.DeleteAsset(AssetDatabase.GUIDToAssetPath(path));
            }

            AssetDatabase.DeleteAsset(ReportPath);
        }

        private static void EnsureAssetFolder(string assetPath)
        {
            Directory.CreateDirectory(Path.Combine(Directory.GetCurrentDirectory(), assetPath));
            AssetDatabase.Refresh();
        }

        private static Transform FindChildByName(Transform root, string name)
        {
            foreach (var child in root.GetComponentsInChildren<Transform>(true))
            {
                if (child.name == name)
                {
                    return child;
                }
            }

            return null;
        }

        private static void RequireObject(UnityEngine.Object value, string description)
        {
            if (value == null)
            {
                throw new InvalidOperationException(
                    $"Required generated scene object is missing: {description}"
                );
            }
        }
    }
}

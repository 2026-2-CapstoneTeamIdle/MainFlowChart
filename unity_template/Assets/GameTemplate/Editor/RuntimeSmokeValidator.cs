using System;
using System.Collections.Generic;
using TeamIdle.GameTemplate.Common;
using TeamIdle.GameTemplate.Core;
using TeamIdle.GameTemplate.Platformer;
using TeamIdle.GameTemplate.Prototype;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace TeamIdle.GameTemplate.Editor
{
    // Host-owned tests: generated modules must not edit this file.
    [InitializeOnLoad]
    public static class RuntimeSmokeValidator
    {
        [Serializable]
        private sealed class PlaytestMetrics
        {
            public bool completed;
            public float elapsed_seconds;
            public int deaths;
            public float stuck_seconds;
            public string last_reached_zone = string.Empty;
            public string failed_transition = string.Empty;
            public List<string> unused_requested_features = new();
            public List<string> passed_scenarios = new();
        }

        private const string Active = "TeamIdle.RuntimeSmoke.Active";
        private static double started;
        private static int frames;
        private static bool failed;
        private static string failureDetail = string.Empty;
        private static Vector3 initialPosition;
        private static Vector3 phaseStartPosition;
        private static GameObject player;
        private static GameObject testWall;
        private static Rigidbody2D playerBody;
        private static AirDashModule airDash;
        private static WallClimbModule wallClimb;
        private static bool movementTest;
        private static bool airDashObserved;
        private static int traversalPhase;
        private static float phaseStartedAt;
        private static ValidationPlan validationPlan;
        private static CollectibleSystemModule collectibleSystem;
        private static GoalSystemModule goalSystem;
        private static PrototypePlatformerStageController stageController;
        private static HealthComponent playerHealth;
        private static PrototypeCollectible[] collectibles = Array.Empty<PrototypeCollectible>();
        private static int collectibleIndex;
        private static int collectedBefore;
        private static PrototypeCheckpoint checkpoint;
        private static PrototypeHazard hazard;
        private static PrototypeGoal goalActor;
        private static float healthBeforeHazard;
        private static readonly HashSet<string> PassedScenarios = new(StringComparer.Ordinal);
        private static readonly PlaytestMetrics Metrics = new();
        private static float runStartedAt;
        private static float routeGoalX;
        private static float routeBestX;
        private static float routeLastProgressAt;
        private static float routePreviousX;
        private static float routeTimeoutSeconds;
        private static readonly List<float> RouteObstacleXs = new();

        static RuntimeSmokeValidator()
        {
            if (SessionState.GetBool(Active, false))
            {
                started = EditorApplication.timeSinceStartup;
                Application.logMessageReceived += OnLog;
                EditorApplication.update += Tick;
            }
        }

        public static void RunForBatch()
        {
            started = EditorApplication.timeSinceStartup;
            frames = 0;
            failed = false;
            failureDetail = string.Empty;
            traversalPhase = 0;
            movementTest = false;
            airDashObserved = false;
            validationPlan = null;
            collectibleSystem = null;
            goalSystem = null;
            stageController = null;
            playerHealth = null;
            collectibles = Array.Empty<PrototypeCollectible>();
            collectibleIndex = 0;
            PassedScenarios.Clear();
            Metrics.completed = false;
            Metrics.elapsed_seconds = 0f;
            Metrics.deaths = 0;
            Metrics.stuck_seconds = 0f;
            Metrics.last_reached_zone = "spawn";
            Metrics.failed_transition = string.Empty;
            Metrics.unused_requested_features.Clear();
            Metrics.passed_scenarios.Clear();
            SessionState.SetBool(Active, true);
            EditorSceneManager.OpenScene(TemplateProjectBuilder.ScenePath);
            EditorApplication.EnterPlaymode();
        }

        private static void OnLog(string message, string stack, LogType type)
        {
            if (
                !failed
                && (type == LogType.Exception || type == LogType.Error || type == LogType.Assert)
            )
            {
                failed = true;
                failureDetail = "runtime.exception: " + message;
                if (!string.IsNullOrWhiteSpace(stack))
                {
                    failureDetail += " | " + stack.Replace('\n', ' ').Replace('\r', ' ');
                }
            }
        }

        private static void Tick()
        {
            if (EditorApplication.timeSinceStartup - started > 30)
            {
                Finish(false, "runtime.timeout: Play Mode did not complete");
                return;
            }
            if (!EditorApplication.isPlaying || EditorApplication.isPaused)
                return;
            if (failed)
            {
                Finish(
                    false,
                    string.IsNullOrWhiteSpace(failureDetail)
                        ? "runtime.exception: unknown Unity error"
                        : failureDetail
                );
                return;
            }
            frames++;
            if (frames == 10)
            {
                foreach (
                    var module in UnityEngine.Object.FindObjectsByType<GameModuleBehaviour>(
                        FindObjectsSortMode.None
                    )
                )
                {
                    if (
                        !module.IsInitialized
                        || (module is IGeneratedFeatureModule feature && !feature.IsFeatureBound)
                    )
                    {
                        Finish(
                            false,
                            "runtime.binding: "
                                + module.ModuleId
                                + " initialized="
                                + module.IsInitialized
                        );
                        return;
                    }
                }
                player = GameObject.Find("Player");
                movementTest =
                    UnityEngine.Object.FindFirstObjectByType<PlatformerMovementModule>() != null;
                if (movementTest && player == null)
                {
                    Finish(false, "runtime.player_missing");
                    return;
                }
                if (player != null)
                {
                    initialPosition = player.transform.position;
                    playerBody = player.GetComponent<Rigidbody2D>();
                }
                airDash = UnityEngine.Object.FindFirstObjectByType<AirDashModule>();
                wallClimb = UnityEngine.Object.FindFirstObjectByType<WallClimbModule>();
                InputAdapterModule.TestInputEnabled = movementTest;
                InputAdapterModule.TestMovement = Vector2.right;
                InputAdapterModule.TestConfirmPressed = false;
                phaseStartedAt = Time.timeSinceLevelLoad;
                runStartedAt = Time.timeSinceLevelLoad;
            }
            if (frames < 10)
                return;
            if (!movementTest)
            {
                var genre = GameBootstrap.Instance?.Config?.Genre ?? "unknown";
                Debug.Log("UNITY_VALIDATION_PLAN_SKIPPED:" + genre);
                Debug.Log("UNITY_VALIDATION_PLAN_OK:0");
                Finish(true, "runtime.smoke: module bindings; genre scenario runner pending");
                return;
            }
            if (Time.timeSinceLevelLoad < 1f)
                return;
            var presentation =
                UnityEngine.Object.FindFirstObjectByType<PrototypePresentationController>();
            if (presentation == null || !presentation.IsInitialized)
            {
                Finish(
                    false,
                    "runtime.presentation: HUD and feedback bindings are not ready: "
                        + (presentation == null ? "controller missing" : presentation.BindingStatus)
                );
                return;
            }
            if (traversalPhase >= 10)
            {
                TickValidationPlan();
                return;
            }
            if (player != null)
            {
                var position = player.transform.position;
                if (
                    float.IsNaN(position.x)
                    || float.IsNaN(position.y)
                    || float.IsInfinity(position.x)
                    || float.IsInfinity(position.y)
                )
                {
                    Finish(false, "runtime.position_non_finite");
                    return;
                }
                if (traversalPhase == 0 && Time.timeSinceLevelLoad - phaseStartedAt >= 0.5f)
                {
                    if (position.x - initialPosition.x < 0.1f)
                    {
                        Finish(
                            false,
                            "runtime.horizontal_movement: right input must move Player by at least 0.1"
                        );
                        return;
                    }

                    if (airDash != null)
                    {
                        BeginAirDashTest();
                        return;
                    }

                    if (wallClimb != null)
                    {
                        BeginWallClimbTest();
                        return;
                    }

                    BeginAutoTraversalTest();
                    return;
                }

                if (traversalPhase == 1)
                {
                    var elapsed = Time.timeSinceLevelLoad - phaseStartedAt;
                    InputAdapterModule.TestDashPressed = elapsed < 0.1f;
                    airDashObserved |= airDash.IsDashing;
                    if (elapsed < 0.35f)
                        return;
                    if (!airDashObserved || position.x - phaseStartPosition.x < 0.5f)
                    {
                        Finish(false, "runtime.air_dash: Player did not receive a dash burst");
                        return;
                    }

                    if (wallClimb != null)
                    {
                        BeginWallClimbTest();
                        return;
                    }

                    BeginAutoTraversalTest();
                    return;
                }

                if (traversalPhase == 2 && Time.timeSinceLevelLoad - phaseStartedAt >= 0.35f)
                {
                    if (position.y - phaseStartPosition.y < 0.2f || !wallClimb.IsClimbing)
                    {
                        Finish(false, "runtime.wall_climb: Player did not climb an adjacent wall");
                        return;
                    }

                    BeginAutoTraversalTest();
                    return;
                }

                if (traversalPhase == 3)
                {
                    TickAutoTraversal(position);
                    return;
                }
            }
        }

        private static void BeginAutoTraversalTest()
        {
            LevelPlan levelPlan;
            try
            {
                levelPlan = LevelPlan.Load();
            }
            catch (Exception error)
            {
                Finish(false, "runtime.level_plan_load: " + error.Message);
                return;
            }

            traversalPhase = 3;
            player.transform.position = new Vector3(
                levelPlan.player_spawn.x,
                levelPlan.player_spawn.y,
                0f
            );
            playerBody.linearVelocity = Vector2.zero;
            Physics2D.SyncTransforms();
            routeGoalX = levelPlan.goal.x - 1f;
            routeBestX = player.transform.position.x;
            routePreviousX = routeBestX;
            var routeDistance = Mathf.Max(0f, routeGoalX - routeBestX);
            routeTimeoutSeconds = Mathf.Clamp(routeDistance / 4f + 4f, 8f, 30f);
            routeLastProgressAt = Time.timeSinceLevelLoad;
            RouteObstacleXs.Clear();
            foreach (var zone in levelPlan.zones)
            {
                foreach (var hazardPlan in zone.hazards)
                {
                    RouteObstacleXs.Add(hazardPlan.x);
                }
                foreach (var enemyPlan in zone.enemies)
                {
                    RouteObstacleXs.Add(enemyPlan.x);
                }
            }
            RouteObstacleXs.Sort();
            phaseStartedAt = Time.timeSinceLevelLoad;
            InputAdapterModule.TestMovement = Vector2.right;
            InputAdapterModule.TestConfirmPressed = true;
        }

        private static void TickAutoTraversal(Vector3 position)
        {
            var now = Time.timeSinceLevelLoad;
            if (position.x < routePreviousX - 3f)
            {
                Metrics.deaths++;
            }
            routePreviousX = position.x;
            foreach (var obstacleX in RouteObstacleXs)
            {
                var distance = obstacleX - position.x;
                if (distance >= 0f && distance < 1.8f && playerBody.linearVelocity.y < 1f)
                {
                    playerBody.linearVelocity = new Vector2(playerBody.linearVelocity.x, 12f);
                    break;
                }
            }
            if (position.x > routeBestX + 0.15f)
            {
                routeBestX = position.x;
                routeLastProgressAt = now;
            }
            if (now - routeLastProgressAt > 1.5f)
            {
                Metrics.stuck_seconds += Time.deltaTime;
            }
            if (position.x >= routeGoalX)
            {
                Metrics.last_reached_zone = "mastery";
                InputAdapterModule.TestConfirmPressed = false;
                BeginValidationPlanTests();
                return;
            }
            if (now - phaseStartedAt > routeTimeoutSeconds)
            {
                Finish(
                    false,
                    $"runtime.route_blocked: best_x={routeBestX:F2}, goal_x={routeGoalX:F2}, "
                        + $"timeout={routeTimeoutSeconds:F2}s"
                );
            }
        }

        private static void BeginValidationPlanTests()
        {
            try
            {
                validationPlan = ValidationPlan.Load();
            }
            catch (Exception error)
            {
                Finish(false, "runtime.validation_plan_load: " + error.Message);
                return;
            }

            foreach (
                var scenarioId in new[]
                {
                    "feature_binding",
                    "checkpoint_recovery",
                    "start_to_goal",
                }
            )
            {
                if (!validationPlan.HasScenario(scenarioId))
                {
                    Finish(false, "runtime.validation_scenario_missing: " + scenarioId);
                    return;
                }
            }

            if (!ValidateRequiredSceneObjects() || !ValidateRuntimeFeatureBindings())
            {
                return;
            }

            collectibleSystem = UnityEngine.Object.FindFirstObjectByType<CollectibleSystemModule>();
            goalSystem = UnityEngine.Object.FindFirstObjectByType<GoalSystemModule>();
            stageController =
                UnityEngine.Object.FindFirstObjectByType<PrototypePlatformerStageController>();
            playerHealth = player.GetComponent<HealthComponent>();
            checkpoint = UnityEngine.Object.FindFirstObjectByType<PrototypeCheckpoint>();
            hazard = UnityEngine.Object.FindFirstObjectByType<PrototypeHazard>();
            goalActor = UnityEngine.Object.FindFirstObjectByType<PrototypeGoal>();
            collectibles = UnityEngine.Object.FindObjectsByType<PrototypeCollectible>(
                FindObjectsSortMode.None
            );
            Array.Sort(collectibles, (left, right) => string.CompareOrdinal(left.name, right.name));
            if (
                collectibleSystem == null
                || goalSystem == null
                || stageController == null
                || playerHealth == null
                || checkpoint == null
                || hazard == null
                || goalActor == null
                || collectibles.Length == 0
            )
            {
                Finish(false, "runtime.validation_fixture_missing");
                return;
            }

            MarkScenarioPassed("feature_binding");
            InputAdapterModule.TestMovement = Vector2.zero;
            InputAdapterModule.TestDashPressed = false;
            InputAdapterModule.TestConfirmPressed = false;
            collectibleIndex = 0;
            BeginCollectibleTest();
        }

        private static bool ValidateRequiredSceneObjects()
        {
            foreach (var objectName in validationPlan.required_scene_objects)
            {
                if (GameObject.Find(objectName) == null)
                {
                    Finish(false, "runtime.required_scene_object_missing: " + objectName);
                    return false;
                }
            }

            return true;
        }

        private static bool ValidateRuntimeFeatureBindings()
        {
            var moduleIds = new HashSet<string>(StringComparer.Ordinal);
            foreach (
                var module in UnityEngine.Object.FindObjectsByType<GameModuleBehaviour>(
                    FindObjectsSortMode.None
                )
            )
            {
                if (module.IsInitialized)
                {
                    moduleIds.Add(module.ModuleId);
                }
            }

            var aliases = new Dictionary<string, string>(StringComparer.Ordinal)
            {
                ["collectible"] = "collectible_system",
                ["goal"] = "goal_system",
                ["health_damage"] = "health_damage_system",
            };
            foreach (var binding in validationPlan.required_feature_bindings)
            {
                var moduleId = aliases.TryGetValue(binding, out var alias) ? alias : binding;
                var isBound = moduleIds.Contains(moduleId);
                if (binding == "health_damage")
                {
                    isBound |= player.GetComponent<HealthComponent>() != null;
                }
                if (!isBound)
                {
                    Metrics.unused_requested_features.Add(binding);
                    Finish(false, "runtime.required_feature_unbound: " + binding);
                    return false;
                }
            }

            return true;
        }

        private static void BeginCollectibleTest()
        {
            traversalPhase = 10;
            collectedBefore = collectibleSystem.CollectedCount;
            TeleportPlayer(collectibles[collectibleIndex].transform.position);
        }

        private static void BeginCheckpointTest()
        {
            traversalPhase = 11;
            TeleportPlayer(checkpoint.transform.position);
        }

        private static void BeginHazardTest()
        {
            traversalPhase = 12;
            playerHealth.SetMaximum(playerHealth.Maximum);
            healthBeforeHazard = playerHealth.Current;
            TeleportPlayer(hazard.transform.position);
        }

        private static void BeginGoalTest()
        {
            traversalPhase = 13;
            TeleportPlayer(goalActor.transform.position);
        }

        private static void TeleportPlayer(Vector3 position)
        {
            player.transform.position = position;
            playerBody.linearVelocity = Vector2.zero;
            Physics2D.SyncTransforms();
            phaseStartedAt = Time.timeSinceLevelLoad;
        }

        private static void TickValidationPlan()
        {
            if (Time.timeSinceLevelLoad - phaseStartedAt < 0.25f)
            {
                return;
            }

            if (traversalPhase == 10)
            {
                if (collectibleSystem.CollectedCount <= collectedBefore)
                {
                    Finish(false, "runtime.collectible_trigger: count did not increase");
                    return;
                }
                collectibleIndex++;
                if (collectibleIndex < collectibles.Length)
                {
                    BeginCollectibleTest();
                    return;
                }
                if (!collectibleSystem.RequirementMet)
                {
                    Finish(
                        false,
                        "runtime.collectible_requirement: all placed rewards were collected"
                    );
                    return;
                }
                BeginCheckpointTest();
                return;
            }

            if (traversalPhase == 11)
            {
                if (stageController.CheckpointIndex < checkpoint.CheckpointIndex)
                {
                    Finish(false, "runtime.checkpoint_trigger: checkpoint was not activated");
                    return;
                }
                BeginHazardTest();
                return;
            }

            if (traversalPhase == 12)
            {
                if (playerHealth.Current >= healthBeforeHazard)
                {
                    Finish(false, "runtime.hazard_damage: player health did not decrease");
                    return;
                }
                Metrics.deaths++;
                if (
                    Vector3.Distance(player.transform.position, stageController.CurrentCheckpoint)
                    > 0.75f
                )
                {
                    var distance = Vector3.Distance(
                        player.transform.position,
                        stageController.CurrentCheckpoint
                    );
                    Finish(
                        false,
                        "runtime.checkpoint_respawn: player did not return to checkpoint; "
                            + $"player={player.transform.position}, "
                            + $"checkpoint={stageController.CurrentCheckpoint}, "
                            + $"distance={distance:F2}"
                    );
                    return;
                }
                MarkScenarioPassed("checkpoint_recovery");
                BeginGoalTest();
                return;
            }

            if (traversalPhase == 13)
            {
                if (!goalSystem.IsCompleted)
                {
                    Finish(false, "runtime.goal_trigger: clear state was not entered");
                    return;
                }
                MarkScenarioPassed("start_to_goal");
                if (PassedScenarios.Count != validationPlan.scenarios.Count)
                {
                    Finish(
                        false,
                        $"runtime.validation_scenario_count: expected={validationPlan.scenarios.Count}, "
                            + $"passed={PassedScenarios.Count}"
                    );
                    return;
                }
                Debug.Log($"UNITY_VALIDATION_PLAN_OK:{PassedScenarios.Count}");
                Finish(true, "runtime.smoke: movement, requested features, recovery, clear flow");
            }
        }

        private static void MarkScenarioPassed(string scenarioId)
        {
            if (PassedScenarios.Add(scenarioId))
            {
                Metrics.passed_scenarios.Add(scenarioId);
                Metrics.last_reached_zone = scenarioId switch
                {
                    "feature_binding" => "tutorial",
                    "checkpoint_recovery" => "challenge",
                    "start_to_goal" => "mastery",
                    _ => Metrics.last_reached_zone,
                };
                Debug.Log("UNITY_VALIDATION_SCENARIO_OK:" + scenarioId);
            }
        }

        private static void BeginAirDashTest()
        {
            traversalPhase = 1;
            player.transform.position = new Vector3(0f, 2f, 0f);
            playerBody.linearVelocity = Vector2.zero;
            phaseStartPosition = player.transform.position;
            phaseStartedAt = Time.timeSinceLevelLoad;
            InputAdapterModule.TestMovement = Vector2.right;
            InputAdapterModule.TestDashPressed = true;
        }

        private static void BeginWallClimbTest()
        {
            traversalPhase = 2;
            InputAdapterModule.TestDashPressed = false;
            InputAdapterModule.TestConfirmPressed = false;
            player.transform.position = new Vector3(0f, 2f, 0f);
            playerBody.linearVelocity = Vector2.zero;
            testWall = new GameObject("RuntimeSmokeWall");
            testWall.transform.position = new Vector3(0.65f, 2f, 0f);
            var collider = testWall.AddComponent<BoxCollider2D>();
            collider.size = new Vector2(0.25f, 4f);
            Physics2D.SyncTransforms();
            phaseStartPosition = player.transform.position;
            phaseStartedAt = Time.timeSinceLevelLoad;
            InputAdapterModule.TestMovement = Vector2.one;
        }

        private static void Finish(bool passed, string detail)
        {
            SessionState.SetBool(Active, false);
            InputAdapterModule.TestInputEnabled = false;
            InputAdapterModule.TestDashPressed = false;
            if (testWall != null)
                UnityEngine.Object.Destroy(testWall);
            EditorApplication.update -= Tick;
            Application.logMessageReceived -= OnLog;
            Metrics.completed = passed;
            Metrics.elapsed_seconds = Mathf.Max(0f, Time.timeSinceLevelLoad - runStartedAt);
            if (!passed)
            {
                var separator = detail.IndexOf(':');
                Metrics.failed_transition = separator >= 0 ? detail[..separator] : detail;
                if (Metrics.failed_transition.Contains("timeout", StringComparison.Ordinal))
                {
                    Metrics.stuck_seconds = Metrics.elapsed_seconds;
                }
            }
            Debug.Log("UNITY_PLAYTEST_METRICS:" + JsonUtility.ToJson(Metrics));
            Debug.Log(
                (passed ? "UNITY_RUNTIME_SMOKE_OK: " : "UNITY_RUNTIME_SMOKE_FAILED: ") + detail
            );
            EditorApplication.Exit(passed ? 0 : 1);
        }
    }
}

using System;
using TeamIdle.GameTemplate.Common;
using TeamIdle.GameTemplate.Core;
using TeamIdle.GameTemplate.Platformer;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace TeamIdle.GameTemplate.Editor
{
    // Host-owned tests: generated modules must not edit this file.
    [InitializeOnLoad]
    public static class RuntimeSmokeValidator
    {
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
                phaseStartedAt = Time.timeSinceLevelLoad;
            }
            if (frames < 10 || !movementTest)
                return;
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

                    Finish(true, "runtime.smoke: bindings, position, platformer movement");
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

                    Finish(true, "runtime.smoke: bindings, movement, air dash");
                    return;
                }

                if (traversalPhase == 2 && Time.timeSinceLevelLoad - phaseStartedAt >= 0.35f)
                {
                    if (position.y - phaseStartPosition.y < 0.2f || !wallClimb.IsClimbing)
                    {
                        Finish(false, "runtime.wall_climb: Player did not climb an adjacent wall");
                        return;
                    }

                    Finish(true, "runtime.smoke: bindings, movement, air dash, wall climb");
                    return;
                }
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
            Debug.Log(
                (passed ? "UNITY_RUNTIME_SMOKE_OK: " : "UNITY_RUNTIME_SMOKE_FAILED: ") + detail
            );
            EditorApplication.Exit(passed ? 0 : 1);
        }
    }
}

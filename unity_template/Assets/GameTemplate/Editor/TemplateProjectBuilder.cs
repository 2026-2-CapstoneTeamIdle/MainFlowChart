using System;
using System.IO;
using TeamIdle.GameTemplate.Core;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace TeamIdle.GameTemplate.Editor
{
    public static class TemplateProjectBuilder
    {
        public const string ScenePath = "Assets/Scenes/Bootstrap.unity";
        public const string ConfigPath = "Assets/GameTemplate/Generated/GameTemplateConfig.asset";
        public const string GenerationRequestPath =
            "Assets/GameTemplate/Generated/GenerationRequest.json";

        [InitializeOnLoadMethod]
        private static void ScheduleGeneratedProjectBuild()
        {
            if (!File.Exists(GenerationRequestPath))
            {
                return;
            }

            EditorApplication.delayCall += () =>
            {
                if (!File.Exists(GenerationRequestPath))
                {
                    return;
                }

                BuildTemplate();
                Debug.Log("UNITY_GENERATED_PROJECT_READY");
            };
        }

        [MenuItem("Tools/Team IDLE/Rebuild Bootstrap Scene")]
        public static void BuildFromMenu()
        {
            BuildTemplate();
            EditorUtility.DisplayDialog("Team IDLE", "Bootstrap scene rebuilt successfully.", "OK");
        }

        public static void BuildForBatch()
        {
            ModuleComponentCatalog.ValidateForBatch();
            BuildTemplate();
            var config = AssetDatabase.LoadAssetAtPath<GameTemplateConfig>(ConfigPath);
            PrefabSceneAssembler.ValidateCurrentSceneForBatch(config);
            Debug.Log("UNITY_TEMPLATE_BUILD_OK");
        }

        private static void BuildTemplate()
        {
            EnsureAssetFolder("Assets/Scenes");
            EnsureAssetFolder("Assets/GameTemplate/Generated");

            EditorSettings.defaultBehaviorMode = EditorBehaviorMode.Mode2D;
            EditorSettings.serializationMode = SerializationMode.ForceText;
            PlayerSettings.companyName = "Team IDLE";
            PlayerSettings.productName = "Generated 2D Game";

            var config = AssetDatabase.LoadAssetAtPath<GameTemplateConfig>(ConfigPath);
            if (config == null)
            {
                config = ScriptableObject.CreateInstance<GameTemplateConfig>();
                AssetDatabase.CreateAsset(config, ConfigPath);
            }

            var configuredModules =
                config.SelectedModules.Count > 0
                    ? config.SelectedModules
                    : new[] { "game_bootstrap", "validation_probe" };
            config.Configure(
                "3.4.0",
                config.GameTitle,
                config.Genre,
                config.Viewpoint,
                ScenePath,
                configuredModules
            );
            EditorUtility.SetDirty(config);

            GeneratedAssetBinder.ImportAndConfigureAssets();
            AssetDatabase.Refresh();

            var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
            scene.name = "Bootstrap";

            var bootstrapObject = new GameObject("GameBootstrap");
            var validationProbe = bootstrapObject.AddComponent<ValidationProbe>();
            var bootstrap = bootstrapObject.AddComponent<GameBootstrap>();
            var moduleRoot = new GameObject("Modules").transform;
            moduleRoot.SetParent(bootstrapObject.transform, false);
            ModuleComponentCatalog.AddConfiguredModules(
                moduleRoot.gameObject,
                config.SelectedModules,
                validationProbe
            );

            var serializedBootstrap = new SerializedObject(bootstrap);
            serializedBootstrap.FindProperty("config").objectReferenceValue = config;
            serializedBootstrap.FindProperty("moduleRoot").objectReferenceValue = moduleRoot;
            serializedBootstrap.FindProperty("validationProbe").objectReferenceValue =
                validationProbe;
            serializedBootstrap.ApplyModifiedPropertiesWithoutUndo();

            var cameraObject = new GameObject("Main Camera", typeof(Camera), typeof(AudioListener));
            cameraObject.tag = "MainCamera";
            cameraObject.transform.position = new Vector3(0f, 0f, -10f);
            var camera = cameraObject.GetComponent<Camera>();
            camera.orthographic = true;
            camera.orthographicSize = 5f;
            camera.clearFlags = CameraClearFlags.SolidColor;
            camera.backgroundColor = new Color(0.035f, 0.04f, 0.055f, 1f);

            PrefabSceneAssembler.Assemble(config, moduleRoot, camera, validationProbe);
            GeneratedAssetBinder.BindSceneAssets(
                moduleRoot,
                GameObject.Find("GeneratedGame").transform
            );

            if (!EditorSceneManager.SaveScene(scene, ScenePath))
            {
                throw new InvalidOperationException(
                    $"Failed to save bootstrap scene at {ScenePath}."
                );
            }

            EditorBuildSettings.scenes = new[] { new EditorBuildSettingsScene(ScenePath, true) };
            AssetDatabase.SaveAssets();
            AssetDatabase.DeleteAsset(GenerationRequestPath);
            AssetDatabase.Refresh();
        }

        private static void EnsureAssetFolder(string assetPath)
        {
            var absolutePath = Path.Combine(Directory.GetCurrentDirectory(), assetPath);
            Directory.CreateDirectory(absolutePath);
        }
    }
}

using System;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.Build;
using UnityEditor.Build.Reporting;
using UnityEditor.SceneManagement;
using UnityEditor.WebGL;
using UnityEngine;

namespace TeamIdle.GameTemplate.Editor
{
    public static class WebGLPreviewBuilder
    {
        private const string OutputArgument = "-webGLPreviewOutput";
        private const string PreviewTemplate = "PROJECT:TeamIdlePreview";
        private const string PreviewShaderResourceFolder =
            "Assets/GameTemplate/Generated/WebGLPreview/Resources/PreviewShaders";

        private static readonly string[] RequiredRuntimeShaders =
        {
            "UI/Default",
            "UI/Default Font",
            "Sprites/Default",
            "GUI/Text Shader",
        };

        public static void BuildForPreview()
        {
            var outputPath = ReadRequiredArgument(OutputArgument);
            PrepareProjectForPreview();

            var scenes = EditorBuildSettings
                .scenes.Where(scene => scene.enabled)
                .Select(scene => scene.path)
                .ToArray();
            if (scenes.Length == 0)
            {
                throw new InvalidOperationException("No enabled scene is available for WebGL.");
            }

            Directory.CreateDirectory(outputPath);
            var previousCompression = PlayerSettings.WebGL.compressionFormat;
            var previousTemplate = PlayerSettings.WebGL.template;
            var previousCodeOptimization = UserBuildSettings.codeOptimization;
            var previousStrippingLevel = PlayerSettings.GetManagedStrippingLevel(
                NamedBuildTarget.WebGL
            );
            var previousStripEngineCode = PlayerSettings.stripEngineCode;
            try
            {
                // LocalWeb serves this loopback-only preview directly. Uncompressed output avoids
                // browser failures caused by missing Content-Encoding headers on static servers.
                PlayerSettings.WebGL.compressionFormat = WebGLCompressionFormat.Disabled;
                UserBuildSettings.codeOptimization = WasmCodeOptimization.BuildTimes;
                PlayerSettings.SetManagedStrippingLevel(
                    NamedBuildTarget.WebGL,
                    ManagedStrippingLevel.Minimal
                );
                PlayerSettings.stripEngineCode = false;
                SelectPreviewTemplate();
                EnsureRuntimeShadersIncluded();
                Debug.Log("WEBGL_PREVIEW_STAGE:script_conversion");
                Debug.Log("WEBGL_PREVIEW_CACHE_REUSE:Library/Bee preserved");
                var report = BuildPipeline.BuildPlayer(
                    new BuildPlayerOptions
                    {
                        scenes = scenes,
                        locationPathName = outputPath,
                        target = BuildTarget.WebGL,
                        options = BuildOptions.Development,
                    }
                );
                if (report.summary.result != BuildResult.Succeeded)
                {
                    throw new InvalidOperationException(
                        $"WebGL build failed: result={report.summary.result}, "
                            + $"errors={report.summary.totalErrors}"
                    );
                }

                Debug.Log($"UNITY_WEBGL_PREVIEW_OK:{Path.GetFullPath(outputPath)}");
            }
            finally
            {
                PlayerSettings.WebGL.compressionFormat = previousCompression;
                PlayerSettings.WebGL.template = previousTemplate;
                UserBuildSettings.codeOptimization = previousCodeOptimization;
                PlayerSettings.SetManagedStrippingLevel(
                    NamedBuildTarget.WebGL,
                    previousStrippingLevel
                );
                PlayerSettings.stripEngineCode = previousStripEngineCode;
                AssetDatabase.SaveAssets();
            }
        }

        private static void PrepareProjectForPreview()
        {
            if (!File.Exists(TemplateProjectBuilder.ScenePath))
            {
                TemplateProjectBuilder.BuildForBatch();
                Debug.Log("WEBGL_PREVIEW_CACHE:bootstrap_rebuilt");
                return;
            }

            try
            {
                // Preview is a publication step, not another generation pass. Rebuilding an
                // already generated scene can replace agent-authored content and invalidate its
                // serialized profile. Keep the project's scene and Library/Bee cache intact.
                EditorSceneManager.OpenScene(
                    TemplateProjectBuilder.ScenePath,
                    OpenSceneMode.Single
                );
                EditorBuildSettings.scenes = new[]
                {
                    new EditorBuildSettingsScene(TemplateProjectBuilder.ScenePath, true),
                };
                Debug.Log("WEBGL_PREVIEW_CACHE:scene_and_Library_Bee_reused");
            }
            catch (Exception error)
            {
                throw new InvalidOperationException(
                    $"Generated preview scene could not be opened: {error.Message}",
                    error
                );
            }
        }

        private static void EnsureRuntimeShadersIncluded()
        {
            Directory.CreateDirectory(PreviewShaderResourceFolder);
            AssetDatabase.Refresh();
            foreach (var shaderName in RequiredRuntimeShaders)
            {
                var shader = Shader.Find(shaderName);
                if (shader == null)
                {
                    Debug.LogWarning($"WEBGL_PREVIEW_SHADER_MISSING:{shaderName}");
                    continue;
                }

                var fileName = shaderName.Replace('/', '_').Replace(' ', '_');
                var assetPath = $"{PreviewShaderResourceFolder}/{fileName}.mat";
                var material = AssetDatabase.LoadAssetAtPath<Material>(assetPath);
                if (material == null)
                {
                    material = new Material(shader) { name = $"Preview_{fileName}" };
                    AssetDatabase.CreateAsset(material, assetPath);
                }
                else if (material.shader != shader)
                {
                    material.shader = shader;
                    EditorUtility.SetDirty(material);
                }
            }

            AssetDatabase.SaveAssets();
            Debug.Log("WEBGL_PREVIEW_SHADERS_OK");
        }

        private static void SelectPreviewTemplate()
        {
            var templateIndex = Path.Combine(
                Application.dataPath,
                "WebGLTemplates",
                "TeamIdlePreview",
                "index.html"
            );
            if (!File.Exists(templateIndex))
            {
                throw new FileNotFoundException(
                    "The LocalWeb project template is missing its WebGL preview page.",
                    templateIndex
                );
            }

            // Use a project-local template so headless builds never depend on Unity Hub's
            // application template cache or an Editor installation-specific template path.
            PlayerSettings.WebGL.template = PreviewTemplate;
        }

        private static string ReadRequiredArgument(string argumentName)
        {
            var arguments = Environment.GetCommandLineArgs();
            for (var index = 0; index < arguments.Length - 1; index++)
            {
                if (
                    string.Equals(
                        arguments[index],
                        argumentName,
                        StringComparison.OrdinalIgnoreCase
                    )
                )
                {
                    var value = arguments[index + 1].Trim();
                    if (!string.IsNullOrWhiteSpace(value))
                    {
                        return Path.GetFullPath(value);
                    }
                }
            }

            throw new ArgumentException($"Missing required command-line argument: {argumentName}");
        }
    }
}

using System;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.Build.Reporting;
using UnityEngine;

namespace TeamIdle.GameTemplate.Editor
{
    public static class WebGLPreviewBuilder
    {
        private const string OutputArgument = "-webGLPreviewOutput";
        private const string PreviewTemplate = "PROJECT:TeamIdlePreview";

        public static void BuildForPreview()
        {
            var outputPath = ReadRequiredArgument(OutputArgument);
            TemplateProjectBuilder.BuildForBatch();

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
            try
            {
                // LocalWeb serves this loopback-only preview directly. Uncompressed output avoids
                // browser failures caused by missing Content-Encoding headers on static servers.
                PlayerSettings.WebGL.compressionFormat = WebGLCompressionFormat.Disabled;
                SelectPreviewTemplate();
                var report = BuildPipeline.BuildPlayer(
                    new BuildPlayerOptions
                    {
                        scenes = scenes,
                        locationPathName = outputPath,
                        target = BuildTarget.WebGL,
                        options = BuildOptions.None,
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
                AssetDatabase.SaveAssets();
            }
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

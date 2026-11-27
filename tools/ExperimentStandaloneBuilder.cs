using System;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.Build.Reporting;
using UnityEngine;

namespace TeamIdle.GameTemplate.Editor
{
    public static class ExperimentStandaloneBuilder
    {
        public static void Build()
        {
            var args = Environment.GetCommandLineArgs();
            var argumentIndex = Array.IndexOf(args, "-experimentOutput");
            if (argumentIndex < 0 || argumentIndex + 1 >= args.Length)
            {
                throw new ArgumentException("Missing -experimentOutput path.");
            }

            var outputPath = Path.GetFullPath(args[argumentIndex + 1]);
            var scenes = EditorBuildSettings
                .scenes.Where(scene => scene.enabled)
                .Select(scene => scene.path)
                .ToArray();
            if (scenes.Length == 0)
            {
                throw new InvalidOperationException(
                    "No enabled scene is available for the player build."
                );
            }

            Directory.CreateDirectory(Path.GetDirectoryName(outputPath));
            var report = BuildPipeline.BuildPlayer(
                new BuildPlayerOptions
                {
                    scenes = scenes,
                    locationPathName = outputPath,
                    target = BuildTarget.StandaloneWindows64,
                    options = BuildOptions.None,
                }
            );
            Debug.Log(
                $"EXPERIMENT_BUILD_RESULT:{report.summary.result};errors={report.summary.totalErrors}"
            );
            if (report.summary.result != BuildResult.Succeeded || !File.Exists(outputPath))
            {
                throw new InvalidOperationException(
                    "Windows player build did not produce an executable."
                );
            }

            Debug.Log($"EXPERIMENT_BUILD_OK:{outputPath}");
        }
    }
}

using System;
using System.Collections;
using System.IO;
using System.Text;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.SceneManagement;
using UnityEngine.TestTools;

namespace TeamIdle.GameTemplate.VisualTests
{
    /// <summary>
    /// Host-owned evidence capture. Run with graphics enabled; -nographics may produce a blank frame.
    /// </summary>
    public sealed class VisualCaptureTests
    {
        private const string ScenePath = "Assets/Scenes/Bootstrap.unity";

        [UnityTest]
        [Category("VisualValidation")]
        public IEnumerator CaptureRepresentativeGameplayFrame()
        {
            var outputPath = Environment.GetEnvironmentVariable("MAINFLOW_VISUAL_CAPTURE_PATH");
            Assert.That(outputPath, Is.Not.Null.And.Not.Empty, "Capture output path is required.");

            yield return SceneManager.LoadSceneAsync(ScenePath, LoadSceneMode.Single);
            Screen.SetResolution(1280, 720, false);
            for (var frame = 0; frame < 30; frame++)
            {
                yield return null;
            }

            Assert.That(Camera.main, Is.Not.Null, "Bootstrap scene needs a MainCamera.");
            Directory.CreateDirectory(Path.GetDirectoryName(outputPath));
            CaptureCamera(Camera.main, outputPath);

            Assert.That(
                File.Exists(outputPath),
                Is.True,
                "Unity did not write the visual capture."
            );
            Assert.That(new FileInfo(outputPath).Length, Is.GreaterThan(128L));
        }

        private static void CaptureCamera(Camera camera, string outputPath)
        {
            const int width = 1280;
            const int height = 720;
            foreach (
                var canvas in UnityEngine.Object.FindObjectsByType<Canvas>(FindObjectsSortMode.None)
            )
            {
                if (canvas.renderMode != RenderMode.ScreenSpaceOverlay)
                {
                    continue;
                }

                canvas.renderMode = RenderMode.ScreenSpaceCamera;
                canvas.worldCamera = camera;
                canvas.planeDistance = 1f;
            }

            var renderTexture = new RenderTexture(width, height, 24, RenderTextureFormat.ARGB32);
            var previousActive = RenderTexture.active;
            var previousTarget = camera.targetTexture;
            var texture = new Texture2D(width, height, TextureFormat.RGB24, false);
            try
            {
                camera.targetTexture = renderTexture;
                RenderTexture.active = renderTexture;
                camera.Render();
                texture.ReadPixels(new Rect(0, 0, width, height), 0, 0);
                texture.Apply();
                WritePpm(outputPath, width, height, texture.GetPixels32());
            }
            finally
            {
                camera.targetTexture = previousTarget;
                RenderTexture.active = previousActive;
                UnityEngine.Object.DestroyImmediate(texture);
                UnityEngine.Object.DestroyImmediate(renderTexture);
            }
        }

        private static void WritePpm(string path, int width, int height, Color32[] pixels)
        {
            using var stream = File.Create(path);
            var header = Encoding.ASCII.GetBytes($"P6\n{width} {height}\n255\n");
            stream.Write(header, 0, header.Length);
            for (var y = height - 1; y >= 0; y--)
            {
                for (var x = 0; x < width; x++)
                {
                    var pixel = pixels[y * width + x];
                    stream.WriteByte(pixel.r);
                    stream.WriteByte(pixel.g);
                    stream.WriteByte(pixel.b);
                }
            }
        }
    }
}

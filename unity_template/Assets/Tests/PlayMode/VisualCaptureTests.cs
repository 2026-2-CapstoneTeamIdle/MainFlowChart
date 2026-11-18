using System;
using System.Collections;
using System.Collections.Generic;
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

        [Serializable]
        private sealed class UiAuditReport
        {
            public int visibleTextCount;
            public List<string> issues = new();
        }

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
            var pixels = CaptureCamera(Camera.main, outputPath);
            var auditPath = Environment.GetEnvironmentVariable("MAINFLOW_UI_AUDIT_PATH");
            if (!string.IsNullOrEmpty(auditPath))
            {
                Directory.CreateDirectory(Path.GetDirectoryName(auditPath));
                File.WriteAllText(
                    auditPath,
                    JsonUtility.ToJson(AuditVisibleUi(pixels, 1280, 720), true)
                );
            }

            Assert.That(
                File.Exists(outputPath),
                Is.True,
                "Unity did not write the visual capture."
            );
            Assert.That(new FileInfo(outputPath).Length, Is.GreaterThan(128L));
        }

        private static UiAuditReport AuditVisibleUi(Color32[] pixels, int width, int height)
        {
            var report = new UiAuditReport();
            Canvas.ForceUpdateCanvases();
            foreach (
                var label in UnityEngine.Object.FindObjectsByType<UnityEngine.UI.Text>(
                    FindObjectsInactive.Exclude,
                    FindObjectsSortMode.None
                )
            )
            {
                if (!label.isActiveAndEnabled || string.IsNullOrWhiteSpace(label.text))
                {
                    continue;
                }
                report.visibleTextCount++;
                var rect = label.rectTransform;
                var canvas = label.GetComponentInParent<Canvas>();
                var camera =
                    canvas != null && canvas.renderMode != RenderMode.ScreenSpaceOverlay
                        ? canvas.worldCamera
                        : null;
                var corners = new Vector3[4];
                rect.GetWorldCorners(corners);
                var min = new Vector2(float.PositiveInfinity, float.PositiveInfinity);
                var max = new Vector2(float.NegativeInfinity, float.NegativeInfinity);
                foreach (var corner in corners)
                {
                    var screen = RectTransformUtility.WorldToScreenPoint(camera, corner);
                    min = Vector2.Min(min, screen);
                    max = Vector2.Max(max, screen);
                }
                if (
                    max.x <= min.x
                    || max.y <= min.y
                    || min.x < 8f
                    || min.y < 8f
                    || max.x > width - 8f
                    || max.y > height - 8f
                )
                {
                    report.issues.Add($"off_screen:{label.name}");
                }
                UnityEngine.UI.Image backing = null;
                for (
                    var ancestor = label.transform.parent;
                    ancestor != null;
                    ancestor = ancestor.parent
                )
                {
                    var candidate = ancestor.GetComponent<UnityEngine.UI.Image>();
                    if (
                        candidate != null
                        && candidate.isActiveAndEnabled
                        && candidate.color.a >= 0.7f
                    )
                    {
                        backing = candidate;
                        break;
                    }
                }
                if (backing == null)
                {
                    report.issues.Add($"missing_backing:{label.name}");
                    continue;
                }
                var foreground = Luminance(label.color);
                var background = Luminance(backing.color);
                var ratio =
                    (Mathf.Max(foreground, background) + 0.05f)
                    / (Mathf.Min(foreground, background) + 0.05f);
                if (ratio < 4.5f)
                {
                    report.issues.Add($"low_contrast:{label.name}:{ratio:0.0}");
                }
                var sampleRatios = new List<float>();
                foreach (
                    var sample in new[]
                    {
                        new Vector2(min.x + 4f, min.y + 4f),
                        new Vector2(max.x - 4f, min.y + 4f),
                        new Vector2(min.x + 4f, max.y - 4f),
                        new Vector2(max.x - 4f, max.y - 4f),
                    }
                )
                {
                    var x = Mathf.Clamp(Mathf.RoundToInt(sample.x), 0, width - 1);
                    var y = Mathf.Clamp(Mathf.RoundToInt(sample.y), 0, height - 1);
                    var captured = Luminance(pixels[y * width + x]);
                    sampleRatios.Add(
                        (Mathf.Max(foreground, captured) + 0.05f)
                            / (Mathf.Min(foreground, captured) + 0.05f)
                    );
                }
                sampleRatios.Sort();
                if (sampleRatios[1] < 4.5f)
                {
                    report.issues.Add($"low_capture_contrast:{label.name}:{sampleRatios[1]:0.0}");
                }
            }
            return report;
        }

        private static float Luminance(Color color)
        {
            static float Linear(float channel) =>
                channel <= 0.04045f
                    ? channel / 12.92f
                    : Mathf.Pow((channel + 0.055f) / 1.055f, 2.4f);
            return 0.2126f * Linear(color.r)
                + 0.7152f * Linear(color.g)
                + 0.0722f * Linear(color.b);
        }

        private static Color32[] CaptureCamera(Camera camera, string outputPath)
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
            Canvas.ForceUpdateCanvases();
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
                var pixels = texture.GetPixels32();
                WritePpm(outputPath, width, height, pixels);
                return pixels;
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

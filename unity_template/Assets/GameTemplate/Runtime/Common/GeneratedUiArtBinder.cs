using System;
using System.Collections.Generic;
using UnityEngine;

namespace TeamIdle.GameTemplate.Common
{
    public sealed class GeneratedUiArtBinder : MonoBehaviour
    {
        [Serializable]
        private sealed class UiArtBinding
        {
            public string assetId = string.Empty;
            public string objectPrefix = string.Empty;
            public Sprite sprite;
        }

        [SerializeField]
        private List<UiArtBinding> bindings = new();

        private float nextScanTime;

        public void Register(string assetId, string objectPrefix, Sprite sprite)
        {
            if (string.IsNullOrWhiteSpace(objectPrefix) || sprite == null)
            {
                return;
            }

            var binding = bindings.Find(item => item.assetId == assetId);
            if (binding == null)
            {
                binding = new UiArtBinding();
                bindings.Add(binding);
            }

            binding.assetId = assetId;
            binding.objectPrefix = objectPrefix;
            binding.sprite = sprite;
            ApplyBindings();
        }

        private void LateUpdate()
        {
            if (Time.unscaledTime < nextScanTime)
            {
                return;
            }

            nextScanTime = Time.unscaledTime + 0.5f;
            ApplyBindings();
        }

        private void ApplyBindings()
        {
            if (bindings.Count == 0 || !gameObject.scene.IsValid())
            {
                return;
            }

            foreach (var root in gameObject.scene.GetRootGameObjects())
            {
                foreach (var image in root.GetComponentsInChildren<UnityEngine.UI.Image>(true))
                {
                    foreach (var binding in bindings)
                    {
                        if (
                            binding.sprite == null
                            || !image.name.StartsWith(
                                binding.objectPrefix,
                                StringComparison.Ordinal
                            )
                        )
                        {
                            continue;
                        }

                        if (image.sprite != binding.sprite)
                        {
                            image.sprite = binding.sprite;
                            image.type =
                                binding.assetId == "hud_panel_frame"
                                    ? UnityEngine.UI.Image.Type.Sliced
                                    : UnityEngine.UI.Image.Type.Simple;
                            image.preserveAspect = binding.assetId != "hud_panel_frame";
                            image.raycastTarget = false;
                        }
                        if (binding.assetId == "hud_panel_frame")
                        {
                            image.color = Color.white;
                            HideFallbackBacking(image);
                        }
                    }
                }
            }
        }

        private static void HideFallbackBacking(UnityEngine.UI.Image decoration)
        {
            if (!decoration.name.StartsWith("HudArt_", StringComparison.Ordinal))
            {
                return;
            }

            var parent = decoration.transform.parent;
            if (
                parent == null
                || !parent.name.Contains("Panel", StringComparison.OrdinalIgnoreCase)
            )
            {
                return;
            }

            var backing = parent.GetComponent<UnityEngine.UI.Image>();
            if (backing == null || parent.GetComponent<UnityEngine.UI.Button>() != null)
            {
                return;
            }

            var color = backing.color;
            color.a = 0f;
            backing.color = color;
            backing.raycastTarget = false;
        }
    }
}

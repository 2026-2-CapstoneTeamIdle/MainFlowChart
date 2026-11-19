using System;
using System.Collections.Generic;
using UnityEngine;

namespace TeamIdle.GameTemplate.Common
{
    public sealed class GeneratedRuntimeSpriteBinder : MonoBehaviour
    {
        [Serializable]
        private sealed class SpriteBinding
        {
            public string assetId = string.Empty;
            public string objectPrefix = string.Empty;
            public Sprite sprite;
            public RuntimeAnimatorController animationController;
            public bool tileBackground;
        }

        [SerializeField]
        private List<SpriteBinding> bindings = new();

        private float nextScanTime;

        public void Register(
            string assetId,
            string objectPrefix,
            Sprite sprite,
            RuntimeAnimatorController animationController = null,
            bool tileBackground = false
        )
        {
            if (string.IsNullOrWhiteSpace(objectPrefix) || sprite == null)
            {
                return;
            }

            var binding = bindings.Find(item =>
                item.assetId == assetId && item.objectPrefix == objectPrefix
            );
            if (binding == null)
            {
                binding = new SpriteBinding();
                bindings.Add(binding);
            }

            binding.assetId = assetId;
            binding.objectPrefix = objectPrefix;
            binding.sprite = sprite;
            binding.animationController = animationController;
            binding.tileBackground = tileBackground;
            ApplyBindings();
        }

        private void LateUpdate()
        {
            if (Time.unscaledTime < nextScanTime)
            {
                return;
            }

            nextScanTime = Time.unscaledTime + 0.25f;
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
                foreach (var renderer in root.GetComponentsInChildren<SpriteRenderer>(true))
                {
                    if (renderer.name == "GeneratedBackgroundTile")
                    {
                        continue;
                    }
                    SpriteBinding selected = null;
                    foreach (var binding in bindings)
                    {
                        if (
                            binding.sprite == null
                            || !MatchesPrefix(renderer.transform, binding.objectPrefix)
                        )
                        {
                            continue;
                        }
                        if (
                            selected == null
                            || binding.objectPrefix.Length > selected.objectPrefix.Length
                        )
                        {
                            selected = binding;
                        }
                    }

                    if (selected == null)
                    {
                        continue;
                    }

                    if (selected.tileBackground)
                    {
                        ApplyTiledBackground(renderer, selected.sprite);
                        continue;
                    }

                    var driver = renderer.GetComponent<GeneratedSpriteAnimationDriver>();
                    var animator = renderer.GetComponent<Animator>();
                    if (selected.animationController != null)
                    {
                        if (animator == null)
                        {
                            animator = renderer.gameObject.AddComponent<Animator>();
                        }
                        if (animator.runtimeAnimatorController != selected.animationController)
                        {
                            animator.runtimeAnimatorController = selected.animationController;
                        }
                        if (driver == null)
                        {
                            driver =
                                renderer.gameObject.AddComponent<GeneratedSpriteAnimationDriver>();
                        }
                        driver.enabled = true;
                    }
                    else
                    {
                        if (driver != null)
                        {
                            driver.enabled = false;
                            if (animator != null)
                            {
                                animator.runtimeAnimatorController = null;
                            }
                        }
                        if (renderer.sprite != selected.sprite)
                        {
                            renderer.sprite = selected.sprite;
                            renderer.color = Color.white;
                        }
                    }
                }
            }
        }

        private static void ApplyTiledBackground(SpriteRenderer source, Sprite sprite)
        {
            var existing = source.transform.Find("GeneratedBackgroundTile");
            var tileRenderer = existing != null ? existing.GetComponent<SpriteRenderer>() : null;
            var targetSize = tileRenderer == null ? (Vector2)source.bounds.size : tileRenderer.size;
            if (tileRenderer == null)
            {
                var localCenter = source.transform.InverseTransformPoint(source.bounds.center);
                var tile = new GameObject("GeneratedBackgroundTile", typeof(SpriteRenderer));
                tile.transform.SetParent(source.transform, false);
                tile.transform.localPosition = localCenter;
                var scale = source.transform.lossyScale;
                tile.transform.localScale = new Vector3(
                    Mathf.Approximately(scale.x, 0f) ? 1f : 1f / scale.x,
                    Mathf.Approximately(scale.y, 0f) ? 1f : 1f / scale.y,
                    1f
                );
                tileRenderer = tile.GetComponent<SpriteRenderer>();
                tileRenderer.sortingLayerID = source.sortingLayerID;
                tileRenderer.sortingOrder = source.sortingOrder;
            }
            tileRenderer.sprite = sprite;
            tileRenderer.drawMode = SpriteDrawMode.Tiled;
            tileRenderer.tileMode = SpriteTileMode.Continuous;
            tileRenderer.size = targetSize;
            tileRenderer.color = Color.white;
            source.enabled = false;
        }

        private static bool MatchesPrefix(Transform current, string prefix)
        {
            while (current != null)
            {
                if (current.name.StartsWith(prefix, StringComparison.Ordinal))
                {
                    return true;
                }
                current = current.parent;
            }
            return false;
        }
    }
}

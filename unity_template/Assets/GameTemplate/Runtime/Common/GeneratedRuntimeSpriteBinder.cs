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
        }

        [SerializeField]
        private List<SpriteBinding> bindings = new();

        private float nextScanTime;

        public void Register(
            string assetId,
            string objectPrefix,
            Sprite sprite,
            RuntimeAnimatorController animationController = null
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
                    foreach (var binding in bindings)
                    {
                        if (
                            binding.sprite == null
                            || !MatchesPrefix(renderer.transform, binding.objectPrefix)
                        )
                        {
                            continue;
                        }

                        if (binding.animationController != null)
                        {
                            var animator = renderer.GetComponent<Animator>();
                            if (animator == null)
                            {
                                animator = renderer.gameObject.AddComponent<Animator>();
                            }
                            if (animator.runtimeAnimatorController != binding.animationController)
                            {
                                animator.runtimeAnimatorController = binding.animationController;
                            }
                            if (renderer.GetComponent<GeneratedSpriteAnimationDriver>() == null)
                            {
                                renderer.gameObject.AddComponent<GeneratedSpriteAnimationDriver>();
                            }
                        }
                        else if (renderer.sprite != binding.sprite)
                        {
                            renderer.sprite = binding.sprite;
                            renderer.color = Color.white;
                        }
                        break;
                    }
                }
            }
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

using System;
using System.Collections.Generic;
using TeamIdle.GameTemplate.Core;
using UnityEngine;

namespace TeamIdle.GameTemplate.Common
{
    // Plays generated sounds when their gameplay cue is raised. Bindings are written by the
    // editor asset binder from AssetBindingManifest.json.
    public sealed class GeneratedAudioCuePlayer : MonoBehaviour
    {
        [Serializable]
        public sealed class Binding
        {
            public string cue = string.Empty;
            public AudioSource source;
            public bool music;
        }

        [SerializeField]
        private List<Binding> bindings = new();

        public IReadOnlyList<Binding> Bindings => bindings;

        public void AddBinding(string cue, AudioSource source, bool music) =>
            bindings.Add(
                new Binding
                {
                    cue = cue,
                    source = source,
                    music = music,
                }
            );

        public void Play(string cue)
        {
            foreach (var binding in bindings)
            {
                if (binding.cue != cue || binding.source == null || binding.source.clip == null)
                {
                    continue;
                }

                if (!binding.music)
                {
                    // One-shot lets rapid repeats (shots, pickups) overlap instead of restarting.
                    binding.source.PlayOneShot(binding.source.clip);
                    continue;
                }

                foreach (var other in bindings)
                {
                    if (other.music && other.source != null && other.cue != cue)
                    {
                        other.source.Stop();
                    }
                }
                if (!binding.source.isPlaying)
                {
                    binding.source.Play();
                }
            }
        }

        private void OnEnable() => GameAudioCues.Raised += Play;

        private void OnDisable() => GameAudioCues.Raised -= Play;

        private void Start() => Play(GameAudioCues.SceneStart);
    }
}

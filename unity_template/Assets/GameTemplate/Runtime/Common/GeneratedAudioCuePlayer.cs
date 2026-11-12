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

        // Several clips can share a cue: music keeps one track per cue, SFX picks one variation.
        public void Play(string cue)
        {
            var playable = bindings.FindAll(binding =>
                binding.cue == cue && binding.source != null && binding.source.clip != null
            );

            var effects = playable.FindAll(binding => !binding.music);
            if (effects.Count > 0)
            {
                var effect = effects[UnityEngine.Random.Range(0, effects.Count)];
                // One-shot lets rapid repeats (shots, pickups) overlap instead of restarting.
                effect.source.PlayOneShot(effect.source.clip);
            }

            var track = playable.Find(binding => binding.music);
            if (track == null)
            {
                return;
            }

            foreach (var other in bindings)
            {
                if (other.music && other != track && other.source != null)
                {
                    other.source.Stop();
                }
            }
            if (!track.source.isPlaying)
            {
                track.source.Play();
            }
        }

        private void OnEnable() => GameAudioCues.Raised += Play;

        private void OnDisable() => GameAudioCues.Raised -= Play;

        private void Start() => Play(GameAudioCues.SceneStart);
    }
}

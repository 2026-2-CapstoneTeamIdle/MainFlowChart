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
            public string group = string.Empty;

            // Captured from the AudioSource at Awake, so Inspector edits to Volume still count.
            [NonSerialized]
            public float baseVolume = 1f;
        }

        private static readonly string[] Groups =
        {
            GameAudioMixer.Music,
            GameAudioMixer.Sfx,
            GameAudioMixer.Ui,
            GameAudioMixer.Voice,
            GameAudioMixer.Ambience,
        };

        [SerializeField]
        private List<Binding> bindings = new();

        // Mixer group output level 1-100 (gain = level / 100; 50 = the asset's normalized level).
        // Saved in the scene as the starting mix and editable live in Play mode; code changes
        // (GameAudioMixer.SetVolume) are mirrored back here.
        [Header("Mixer Group Volume (1-100, 50 = original)")]
        [SerializeField, Range(1, 100)]
        private int musicVolume = 50;

        [SerializeField, Range(1, 100)]
        private int sfxVolume = 50;

        [SerializeField, Range(1, 100)]
        private int uiVolume = 50;

        [SerializeField, Range(1, 100)]
        private int voiceVolume = 50;

        [SerializeField, Range(1, 100)]
        private int ambienceVolume = 50;

        public IReadOnlyList<Binding> Bindings => bindings;

        public void AddBinding(string cue, AudioSource source, bool music, string group = "") =>
            bindings.Add(
                new Binding
                {
                    cue = cue,
                    source = source,
                    music = music,
                    group = group ?? string.Empty,
                    baseVolume = source != null ? source.volume : 1f,
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
                effect.source.PlayOneShot(
                    effect.source.clip,
                    GameAudioMixer.GetVolume(effect.group)
                );
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
            ApplyVolume(track);
            if (!track.source.isPlaying)
            {
                track.source.Play();
            }
        }

        // One-shots take the group volume at play time; looping tracks follow it live.
        private void OnGroupVolumeChanged(string group)
        {
            SetGroupField(group, ToLevel(GameAudioMixer.GetVolume(group)));
            foreach (var binding in bindings)
            {
                if (binding.music && binding.group == group && binding.source != null)
                {
                    ApplyVolume(binding);
                }
            }
        }

        private static void ApplyVolume(Binding binding) =>
            binding.source.volume = binding.baseVolume * GameAudioMixer.GetVolume(binding.group);

        private static int ToLevel(float gain) =>
            Mathf.Clamp(Mathf.RoundToInt(gain * 100f), 1, 100);

        private float GroupGain(string group) =>
            (
                group switch
                {
                    GameAudioMixer.Music => musicVolume,
                    GameAudioMixer.Sfx => sfxVolume,
                    GameAudioMixer.Ui => uiVolume,
                    GameAudioMixer.Voice => voiceVolume,
                    GameAudioMixer.Ambience => ambienceVolume,
                    _ => 50,
                }
            ) / 100f;

        private void SetGroupField(string group, int volume)
        {
            switch (group)
            {
                case GameAudioMixer.Music:
                    musicVolume = volume;
                    break;
                case GameAudioMixer.Sfx:
                    sfxVolume = volume;
                    break;
                case GameAudioMixer.Ui:
                    uiVolume = volume;
                    break;
                case GameAudioMixer.Voice:
                    voiceVolume = volume;
                    break;
                case GameAudioMixer.Ambience:
                    ambienceVolume = volume;
                    break;
            }
        }

        private void Awake()
        {
            foreach (var binding in bindings)
            {
                if (binding.source != null)
                {
                    binding.baseVolume = binding.source.volume;
                }
            }
            foreach (var group in Groups)
            {
                // A volume already set this session (options menu, previous scene) wins over
                // the scene's saved starting mix, so it survives scene reloads.
                if (GameAudioMixer.HasVolume(group))
                {
                    SetGroupField(group, ToLevel(GameAudioMixer.GetVolume(group)));
                }
                else
                {
                    GameAudioMixer.SetVolume(group, GroupGain(group));
                }
            }
        }

        // Inspector slider moved during Play mode: push it to the shared mixer.
        private void OnValidate()
        {
            if (!Application.isPlaying)
            {
                return;
            }
            foreach (var group in Groups)
            {
                if (!Mathf.Approximately(GameAudioMixer.GetVolume(group), GroupGain(group)))
                {
                    GameAudioMixer.SetVolume(group, GroupGain(group));
                }
            }
        }

        private void OnEnable()
        {
            GameAudioCues.Raised += Play;
            GameAudioMixer.VolumeChanged += OnGroupVolumeChanged;
        }

        private void OnDisable()
        {
            GameAudioCues.Raised -= Play;
            GameAudioMixer.VolumeChanged -= OnGroupVolumeChanged;
        }

        private void Start() => Play(GameAudioCues.SceneStart);
    }
}

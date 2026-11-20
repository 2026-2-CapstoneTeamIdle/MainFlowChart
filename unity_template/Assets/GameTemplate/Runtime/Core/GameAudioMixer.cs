using System;
using System.Collections.Generic;
using UnityEngine;

namespace TeamIdle.GameTemplate.Core
{
    // Code-only mixer groups. A real AudioMixer asset needs the Editor's Audio Mixer window to
    // author (no public API), and Web builds only support per-group volume on it anyway.
    // Keep the group names in sync with mixer_group in game_pipeline/asset_specs.py.
    //
    // Volume is the linear gain applied to each sound (UI level 1-100 = gain 0.01-1.00).
    // The default 0.5 (level 50) plays every generated sound at its loudness-normalized level
    // with 6 dB of headroom, because AudioSource.volume cannot exceed 1.0.
    public static class GameAudioMixer
    {
        public const string Music = "Music";
        public const string Sfx = "SFX";
        public const string Ui = "UI";
        public const string Voice = "Voice";
        public const string Ambience = "Ambience";

        public const float DefaultVolume = 0.5f;

        private static readonly Dictionary<string, float> Volumes = new();

        public static event Action<string> VolumeChanged;

        public static float GetVolume(string group) =>
            !string.IsNullOrEmpty(group) && Volumes.TryGetValue(group, out var volume)
                ? volume
                : DefaultVolume;

        public static bool HasVolume(string group) =>
            !string.IsNullOrEmpty(group) && Volumes.ContainsKey(group);

        public static void SetVolume(string group, float volume)
        {
            Volumes[group] = Mathf.Clamp01(volume);
            VolumeChanged?.Invoke(group);
        }

        // Static state survives play sessions when domain reload is disabled.
        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.SubsystemRegistration)]
        private static void ResetVolumes() => Volumes.Clear();
    }
}

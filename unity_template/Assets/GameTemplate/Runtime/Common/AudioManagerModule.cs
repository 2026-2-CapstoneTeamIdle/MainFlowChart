using TeamIdle.GameTemplate.Core;
using UnityEngine;

namespace TeamIdle.GameTemplate.Common
{
    public sealed class AudioManagerModule : GameModuleBehaviour
    {
        [SerializeField]
        private AudioSource musicSource;

        [SerializeField]
        private AudioSource effectsSource;
        public override string ModuleId => "audio_manager";
        public float MasterVolume => AudioListener.volume;
        public float MusicVolume => musicSource != null ? musicSource.volume : 0f;
        public float EffectsVolume => effectsSource != null ? effectsSource.volume : 0f;

        public void PlayMusic(AudioClip clip, bool loop = true)
        {
            if (musicSource == null || clip == null)
                return;
            musicSource.clip = clip;
            musicSource.loop = loop;
            musicSource.Play();
        }

        public void PlayEffect(AudioClip clip, float volume = 1f)
        {
            if (effectsSource != null && clip != null)
                effectsSource.PlayOneShot(clip, Mathf.Clamp01(volume));
        }

        public void SetMasterVolume(float value) => AudioListener.volume = Mathf.Clamp01(value);

        public void SetMusicVolume(float value)
        {
            if (musicSource != null)
                musicSource.volume = Mathf.Clamp01(value);
        }

        public void SetEffectsVolume(float value)
        {
            if (effectsSource != null)
                effectsSource.volume = Mathf.Clamp01(value);
        }

        protected override void OnInitialize(GameContext context)
        {
            musicSource ??= gameObject.AddComponent<AudioSource>();
            effectsSource ??= gameObject.AddComponent<AudioSource>();
            context.Register(this);
        }
    }
}

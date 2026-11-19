using System;
using System.Collections;
using System.Linq;
using System.Reflection;
using NUnit.Framework;
using TeamIdle.GameTemplate.Common;
using TeamIdle.GameTemplate.Core;
using UnityEngine;
using UnityEngine.TestTools;
using Object = UnityEngine.Object;

namespace TeamIdle.GameTemplate.FeatureTests
{
    /// <summary>
    /// Template regression tests for generated sound playback. No category, so the generated
    /// feature checklist run (-testCategory) does not pick them up.
    /// </summary>
    public sealed class GeneratedAudioCuePlayerTests
    {
        private GameObject root;
        private GeneratedAudioCuePlayer player;

        [SetUp]
        public void SetUp()
        {
            root = new GameObject("AudioCueTest");
            root.SetActive(false);
            player = root.AddComponent<GeneratedAudioCuePlayer>();
        }

        [TearDown]
        public void TearDown() => Object.Destroy(root);

        [UnityTest]
        public IEnumerator SceneStartPlaysOnlyOneMusicTrack()
        {
            var first = AddSource(GameAudioCues.SceneStart, true);
            var second = AddSource(GameAudioCues.SceneStart, true);
            var clear = AddSource(GameAudioCues.GameClear, true);

            root.SetActive(true);
            yield return null;

            Assert.That(first.isPlaying, Is.True);
            Assert.That(second.isPlaying, Is.False);
            Assert.That(clear.isPlaying, Is.False);
        }

        [UnityTest]
        public IEnumerator GameClearStopsSceneMusic()
        {
            var bgm = AddSource(GameAudioCues.SceneStart, true);
            var clear = AddSource(GameAudioCues.GameClear, true);
            root.SetActive(true);
            yield return null;

            GameAudioCues.Raise(GameAudioCues.GameClear);
            yield return null;

            Assert.That(bgm.isPlaying, Is.False);
            Assert.That(clear.isPlaying, Is.True);
        }

        [UnityTest]
        public IEnumerator SameCueEffectsPlayOneVariation()
        {
            var sources = new[]
            {
                AddSource(GameAudioCues.Attack, false),
                AddSource(GameAudioCues.Attack, false),
                AddSource(GameAudioCues.Attack, false),
            };
            root.SetActive(true);
            yield return null;

            GameAudioCues.Raise(GameAudioCues.Attack);
            yield return null;

            Assert.That(sources.Count(source => source.isPlaying), Is.EqualTo(1));
        }

        [UnityTest]
        public IEnumerator MusicFollowsItsMixerGroupVolume()
        {
            var bgm = AddSource(GameAudioCues.SceneStart, true, GameAudioMixer.Music);
            var other = AddSource(GameAudioCues.GameClear, true, GameAudioMixer.Ambience);
            root.SetActive(true);
            yield return null;

            GameAudioMixer.SetVolume(GameAudioMixer.Music, 0.25f);

            Assert.That(bgm.volume, Is.EqualTo(0.25f).Within(1e-4f));
            Assert.That(other.volume, Is.EqualTo(1f));
            GameAudioMixer.SetVolume(GameAudioMixer.Music, GameAudioMixer.DefaultVolume);
        }

        [UnityTest]
        public IEnumerator SourceVolumeIsKeptAsBaseUnderGroupVolume()
        {
            var bgm = AddSource(GameAudioCues.SceneStart, true, GameAudioMixer.Music);
            bgm.volume = 0.5f; // set in the Inspector after binding
            root.SetActive(true);
            yield return null;

            GameAudioMixer.SetVolume(GameAudioMixer.Music, 0.5f);

            Assert.That(bgm.volume, Is.EqualTo(0.25f).Within(1e-4f));
            GameAudioMixer.SetVolume(GameAudioMixer.Music, GameAudioMixer.DefaultVolume);
        }

        [UnityTest]
        public IEnumerator DefaultLevelFiftyPlaysAtHalfGain()
        {
            var bgm = AddSource(GameAudioCues.SceneStart, true, GameAudioMixer.Voice);
            root.SetActive(true);
            yield return null;

            Assert.That(bgm.volume, Is.EqualTo(0.5f).Within(1e-4f));
        }

        [UnityTest]
        public IEnumerator CodeVolumeChangeIsMirroredToInspectorSlider()
        {
            root.SetActive(true);
            yield return null;

            GameAudioMixer.SetVolume(GameAudioMixer.Sfx, 0.4f);

            var slider = typeof(GeneratedAudioCuePlayer).GetField(
                "sfxVolume",
                BindingFlags.NonPublic | BindingFlags.Instance
            );
            Assert.That((int)slider.GetValue(player), Is.EqualTo(40));
            GameAudioMixer.SetVolume(GameAudioMixer.Sfx, GameAudioMixer.DefaultVolume);
        }

        [UnityTest]
        public IEnumerator InspectorChangeToOtherGroupKeepsApiMute()
        {
            root.SetActive(true);
            yield return null;

            GameAudioMixer.SetVolume(GameAudioMixer.Music, 0f); // muted from code
            SetSlider("sfxVolume", 80); // then another group's slider moves in the Inspector

            Assert.That(GameAudioMixer.GetVolume(GameAudioMixer.Music), Is.EqualTo(0f));
            Assert.That(
                GameAudioMixer.GetVolume(GameAudioMixer.Sfx),
                Is.EqualTo(0.8f).Within(1e-4f)
            );
            GameAudioMixer.SetVolume(GameAudioMixer.Music, GameAudioMixer.DefaultVolume);
            GameAudioMixer.SetVolume(GameAudioMixer.Sfx, GameAudioMixer.DefaultVolume);
        }

        [UnityTest]
        public IEnumerator ReenablingDoesNotDuplicateSubscription()
        {
            var before = RaisedHandlerCount();
            for (var cycle = 0; cycle < 3; cycle++)
            {
                root.SetActive(true);
                root.SetActive(false);
            }
            root.SetActive(true);
            yield return null;

            Assert.That(RaisedHandlerCount(), Is.EqualTo(before + 1));
            root.SetActive(false);
            Assert.That(RaisedHandlerCount(), Is.EqualTo(before));
        }

        private AudioSource AddSource(string cue, bool music, string group = "")
        {
            var source = new GameObject(cue).AddComponent<AudioSource>();
            source.transform.SetParent(root.transform);
            source.playOnAwake = false;
            source.loop = music;
            source.clip = AudioClip.Create(cue, 44100, 1, 44100, false);
            player.AddBinding(cue, source, music, group);
            return source;
        }

        // Simulates an Inspector edit: Unity sets the serialized field, then calls OnValidate.
        private void SetSlider(string field, int level)
        {
            const BindingFlags flags = BindingFlags.NonPublic | BindingFlags.Instance;
            typeof(GeneratedAudioCuePlayer).GetField(field, flags).SetValue(player, level);
            typeof(GeneratedAudioCuePlayer).GetMethod("OnValidate", flags).Invoke(player, null);
        }

        private static int RaisedHandlerCount()
        {
            var field = typeof(GameAudioCues).GetField(
                nameof(GameAudioCues.Raised),
                BindingFlags.NonPublic | BindingFlags.Static
            );
            var handlers = (Delegate)field.GetValue(null);
            return handlers?.GetInvocationList().Length ?? 0;
        }
    }
}

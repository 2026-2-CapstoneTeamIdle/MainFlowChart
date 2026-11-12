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

        private AudioSource AddSource(string cue, bool music)
        {
            var source = new GameObject(cue).AddComponent<AudioSource>();
            source.transform.SetParent(root.transform);
            source.playOnAwake = false;
            source.loop = music;
            source.clip = AudioClip.Create(cue, 44100, 1, 44100, false);
            player.AddBinding(cue, source, music);
            return source;
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

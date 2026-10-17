using System;
using System.Collections;
using System.Collections.Generic;
using TeamIdle.GameTemplate.Core;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace TeamIdle.GameTemplate.Common
{
    public sealed class InputAdapterModule : GameModuleBehaviour
    {
        public override string ModuleId => "input_adapter";

#if UNITY_EDITOR
        public static bool TestInputEnabled;
        public static Vector2 TestMovement;
        public static bool TestDashPressed;
        public static bool TestConfirmPressed;
#endif

        public Vector2 Movement =>
#if UNITY_EDITOR
            TestInputEnabled
                ? TestMovement
                :
#endif
                new(Input.GetAxisRaw("Horizontal"), Input.GetAxisRaw("Vertical"));

        public bool ConfirmPressed =>
#if UNITY_EDITOR
            TestInputEnabled
                ? TestConfirmPressed
                :
#endif
                Input.GetButtonDown("Submit") || Input.GetKeyDown(KeyCode.Space);

        public bool CancelPressed =>
            Input.GetButtonDown("Cancel") || Input.GetKeyDown(KeyCode.Escape);

        public bool DashPressed =>
#if UNITY_EDITOR
            TestInputEnabled
                ? TestDashPressed
                :
#endif
                Input.GetKeyDown(KeyCode.LeftShift) || Input.GetKeyDown(KeyCode.RightShift);

        protected override void OnInitialize(GameContext context)
        {
            context.Register(this);
        }
    }

    public sealed class SceneFlowManagerModule : GameModuleBehaviour
    {
        private bool isLoading;

        public override string ModuleId => "scene_flow_manager";

        public bool IsLoading => isLoading;

        public event Action<string> SceneLoaded;

        public void Load(string sceneName)
        {
            if (!isLoading && !string.IsNullOrWhiteSpace(sceneName))
            {
                StartCoroutine(LoadRoutine(sceneName));
            }
        }

        public void ReloadCurrent()
        {
            Load(SceneManager.GetActiveScene().name);
        }

        protected override void OnInitialize(GameContext context)
        {
            context.Register(this);
        }

        private IEnumerator LoadRoutine(string sceneName)
        {
            isLoading = true;
            var operation = SceneManager.LoadSceneAsync(sceneName);
            if (operation == null)
            {
                isLoading = false;
                yield break;
            }

            yield return operation;
            isLoading = false;
            SceneLoaded?.Invoke(sceneName);
        }
    }

    public sealed class AudioManagerModule : GameModuleBehaviour
    {
        [SerializeField]
        private AudioSource musicSource;

        [SerializeField]
        private AudioSource effectsSource;

        public override string ModuleId => "audio_manager";

        public void PlayMusic(AudioClip clip, bool loop = true)
        {
            if (musicSource == null || clip == null)
            {
                return;
            }

            musicSource.clip = clip;
            musicSource.loop = loop;
            musicSource.Play();
        }

        public void PlayEffect(AudioClip clip, float volume = 1f)
        {
            if (effectsSource != null && clip != null)
            {
                effectsSource.PlayOneShot(clip, Mathf.Clamp01(volume));
            }
        }

        protected override void OnInitialize(GameContext context)
        {
            musicSource ??= gameObject.AddComponent<AudioSource>();
            if (effectsSource == null)
            {
                effectsSource = gameObject.AddComponent<AudioSource>();
            }

            context.Register(this);
        }
    }

    public sealed class UiRouterModule : GameModuleBehaviour
    {
        [Serializable]
        private sealed class Route
        {
            public string routeId = string.Empty;
            public GameObject panel;
        }

        [SerializeField]
        private List<Route> routes = new();

        public override string ModuleId => "ui_router";

        public string CurrentRoute { get; private set; } = string.Empty;

        public bool Show(string routeId)
        {
            var found = false;
            foreach (var route in routes)
            {
                var active = route.routeId == routeId;
                if (route.panel != null)
                {
                    route.panel.SetActive(active);
                }

                found |= active;
            }

            if (found)
            {
                CurrentRoute = routeId;
            }

            return found;
        }

        protected override void OnInitialize(GameContext context)
        {
            context.Register(this);
        }
    }

    public sealed class AssetRegistryModule : GameModuleBehaviour
    {
        [Serializable]
        private sealed class AssetEntry
        {
            public string assetId = string.Empty;
            public UnityEngine.Object asset;
        }

        [SerializeField]
        private List<AssetEntry> assets = new();

        private readonly Dictionary<string, UnityEngine.Object> lookup = new(
            StringComparer.Ordinal
        );

        public override string ModuleId => "asset_registry";

        public bool TryGet<T>(string assetId, out T asset)
            where T : UnityEngine.Object
        {
            if (lookup.TryGetValue(assetId, out var value) && value is T typedAsset)
            {
                asset = typedAsset;
                return true;
            }

            asset = null;
            return false;
        }

        protected override void OnInitialize(GameContext context)
        {
            lookup.Clear();
            foreach (var entry in assets)
            {
                if (!string.IsNullOrWhiteSpace(entry.assetId) && entry.asset != null)
                {
                    lookup[entry.assetId] = entry.asset;
                }
            }

            context.Register(this);
        }
    }
}

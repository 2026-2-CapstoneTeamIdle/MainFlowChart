using System;
using TeamIdle.GameTemplate.Core;
using UnityEngine;

namespace TeamIdle.GameTemplate.Common
{
    public sealed class OptionsMenuModule : GameModuleBehaviour
    {
        [SerializeField]
        private KeyCode toggleKey = KeyCode.Escape;

        [SerializeField]
        [Range(0f, 1f)]
        private float volumeStep = 0.1f;

        private AudioManagerModule audioManager;
        private GameObject panel;
        private UnityEngine.UI.Text volumeText;
        private float previousTimeScale = 1f;

        public override string ModuleId => "options_menu";
        public bool IsOpen { get; private set; }
        public float MasterVolume => AudioListener.volume;
        public event Action<bool> VisibilityChanged;
        public event Action QuitRequested;

        private void Update()
        {
            if (Input.GetKeyDown(toggleKey))
                Toggle();
        }

        public void Toggle()
        {
            if (IsOpen)
                Close();
            else
                Open();
        }

        public void Open()
        {
            if (IsOpen)
                return;
            previousTimeScale = Time.timeScale;
            Time.timeScale = 0f;
            IsOpen = true;
            panel.SetActive(true);
            VisibilityChanged?.Invoke(true);
        }

        public void Close()
        {
            if (!IsOpen)
                return;
            Time.timeScale = previousTimeScale;
            IsOpen = false;
            panel.SetActive(false);
            VisibilityChanged?.Invoke(false);
        }

        public void SetMasterVolume(float value)
        {
            var volume = Mathf.Clamp01(value);
            if (audioManager != null)
                audioManager.SetMasterVolume(volume);
            else
                AudioListener.volume = volume;
            RefreshVolumeText();
        }

        public void RequestQuit()
        {
            QuitRequested?.Invoke();
#if !UNITY_EDITOR
            Application.Quit();
#endif
        }

        protected override void OnInitialize(GameContext context)
        {
            context.TryGet(out audioManager);
            BuildView();
            panel.SetActive(false);
            context.Register(this);
        }

        protected override void OnShutdown()
        {
            if (IsOpen)
                Close();
            if (panel != null)
                Destroy(panel);
        }

        private void BuildView()
        {
            var root = RuntimeFeatureUi.CreatePanel(
                "OptionsPanel",
                new Vector2(0.35f, 0.25f),
                new Vector2(0.65f, 0.75f),
                new Color(0.04f, 0.06f, 0.1f, 0.96f)
            );
            panel = root.gameObject;
            RuntimeFeatureUi.CreateText(
                "Title",
                root,
                "OPTIONS (ESC)",
                30,
                new Vector2(0f, 0.8f),
                new Vector2(1f, 1f)
            );
            volumeText = RuntimeFeatureUi.CreateText(
                "Volume",
                root,
                string.Empty,
                22,
                new Vector2(0f, 0.58f),
                new Vector2(1f, 0.8f)
            );
            RuntimeFeatureUi.CreateButton(
                "VolumeDown",
                root,
                "Volume -",
                new Vector2(0f, 0.38f),
                new Vector2(0.5f, 0.58f),
                () => SetMasterVolume(MasterVolume - volumeStep)
            );
            RuntimeFeatureUi.CreateButton(
                "VolumeUp",
                root,
                "Volume +",
                new Vector2(0.5f, 0.38f),
                new Vector2(1f, 0.58f),
                () => SetMasterVolume(MasterVolume + volumeStep)
            );
            RuntimeFeatureUi.CreateButton(
                "Resume",
                root,
                "Resume",
                new Vector2(0f, 0.18f),
                new Vector2(0.5f, 0.38f),
                Close
            );
            RuntimeFeatureUi.CreateButton(
                "Quit",
                root,
                "Quit",
                new Vector2(0.5f, 0.18f),
                new Vector2(1f, 0.38f),
                RequestQuit
            );
            RefreshVolumeText();
        }

        private void RefreshVolumeText()
        {
            if (volumeText != null)
                volumeText.text = $"Master volume: {Mathf.RoundToInt(MasterVolume * 100f)}%";
        }
    }
}

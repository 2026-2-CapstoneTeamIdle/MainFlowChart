using System;
using UnityEngine;
using UnityEngine.EventSystems;

namespace TeamIdle.GameTemplate.Common
{
    internal static class RuntimeFeatureUi
    {
        public static RectTransform CreatePanel(
            string name,
            Vector2 anchorMin,
            Vector2 anchorMax,
            Color color
        )
        {
            var canvas = GetOrCreateCanvas();
            var instance = new GameObject(name, typeof(RectTransform));
            instance.transform.SetParent(canvas.transform, false);
            var rect = (RectTransform)instance.transform;
            rect.anchorMin = anchorMin;
            rect.anchorMax = anchorMax;
            rect.offsetMin = Vector2.zero;
            rect.offsetMax = Vector2.zero;
            instance.AddComponent<UnityEngine.UI.Image>().color = color;
            return rect;
        }

        public static UnityEngine.UI.Text CreateText(
            string name,
            Transform parent,
            string content,
            int fontSize,
            Vector2 anchorMin,
            Vector2 anchorMax
        )
        {
            var instance = new GameObject(name, typeof(RectTransform));
            instance.transform.SetParent(parent, false);
            var rect = (RectTransform)instance.transform;
            rect.anchorMin = anchorMin;
            rect.anchorMax = anchorMax;
            rect.offsetMin = new Vector2(12f, 8f);
            rect.offsetMax = new Vector2(-12f, -8f);
            var text = instance.AddComponent<UnityEngine.UI.Text>();
            text.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            text.fontSize = fontSize;
            text.alignment = TextAnchor.MiddleLeft;
            text.color = Color.white;
            text.text = content;
            text.raycastTarget = false;
            return text;
        }

        public static UnityEngine.UI.Button CreateButton(
            string name,
            Transform parent,
            string label,
            Vector2 anchorMin,
            Vector2 anchorMax,
            Action onClick
        )
        {
            var instance = new GameObject(name, typeof(RectTransform));
            instance.transform.SetParent(parent, false);
            var rect = (RectTransform)instance.transform;
            rect.anchorMin = anchorMin;
            rect.anchorMax = anchorMax;
            rect.offsetMin = new Vector2(8f, 8f);
            rect.offsetMax = new Vector2(-8f, -8f);
            instance.AddComponent<UnityEngine.UI.Image>().color = new Color(0.2f, 0.25f, 0.32f, 1f);
            var button = instance.AddComponent<UnityEngine.UI.Button>();
            button.onClick.AddListener(() => onClick());
            var text = CreateText(
                "Label",
                instance.transform,
                label,
                20,
                Vector2.zero,
                Vector2.one
            );
            text.alignment = TextAnchor.MiddleCenter;
            return button;
        }

        private static Canvas GetOrCreateCanvas()
        {
            var existing = GameObject.Find("FeatureOverlayCanvas");
            if (existing != null && existing.TryGetComponent<Canvas>(out var found))
            {
                EnsureEventSystem();
                return found;
            }

            var canvasObject = new GameObject("FeatureOverlayCanvas", typeof(RectTransform));
            UnityEngine.Object.DontDestroyOnLoad(canvasObject);
            var canvas = canvasObject.AddComponent<Canvas>();
            canvas.renderMode = RenderMode.ScreenSpaceOverlay;
            canvas.sortingOrder = 100;
            var scaler = canvasObject.AddComponent<UnityEngine.UI.CanvasScaler>();
            scaler.uiScaleMode = UnityEngine.UI.CanvasScaler.ScaleMode.ScaleWithScreenSize;
            scaler.referenceResolution = new Vector2(1920f, 1080f);
            canvasObject.AddComponent<UnityEngine.UI.GraphicRaycaster>();

            EnsureEventSystem();

            return canvas;
        }

        private static void EnsureEventSystem()
        {
            if (UnityEngine.Object.FindFirstObjectByType<EventSystem>() != null)
                return;

            var eventSystem = new GameObject("FeatureEventSystem");
            UnityEngine.Object.DontDestroyOnLoad(eventSystem);
            eventSystem.AddComponent<EventSystem>();
            eventSystem.AddComponent<StandaloneInputModule>();
        }
    }
}

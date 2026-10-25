using System;
using TeamIdle.GameTemplate.Common;
using TeamIdle.GameTemplate.Platformer;
using TeamIdle.GameTemplate.Prototype;
using UnityEngine;

namespace TeamIdle.GameTemplate.Editor
{
    public static class PresentationSceneAssembler
    {
        public static PrototypePresentationController AssemblePlatformer(
            Transform uiRoot,
            Transform entityRoot,
            GameObject player,
            Camera sceneCamera,
            PrototypePlatformerStageController stage,
            PresentationPlan plan,
            CollectibleSystemModule collectibles,
            GoalSystemModule goal
        )
        {
            if (!plan.ui_screens.Contains("hud"))
            {
                throw new InvalidOperationException("Platformer presentation plan requires a HUD.");
            }

            var canvasObject = new GameObject("PresentationCanvas", typeof(RectTransform));
            canvasObject.transform.SetParent(uiRoot, false);
            var canvas = canvasObject.AddComponent<Canvas>();
            canvas.renderMode = RenderMode.ScreenSpaceOverlay;
            canvas.sortingOrder = 100;
            var scaler = canvasObject.AddComponent<UnityEngine.UI.CanvasScaler>();
            scaler.uiScaleMode = UnityEngine.UI.CanvasScaler.ScaleMode.ScaleWithScreenSize;
            scaler.referenceResolution = new Vector2(1920f, 1080f);
            scaler.matchWidthOrHeight = 0.5f;
            canvasObject.AddComponent<UnityEngine.UI.GraphicRaycaster>();

            var topPanel = CreateImage(
                "TopStatusPanel",
                canvasObject.transform,
                new Color(0.035f, 0.045f, 0.075f, 0.9f)
            );
            Anchor(topPanel.rectTransform, new Vector2(0f, 1f), new Vector2(0f, 1f));
            topPanel.rectTransform.pivot = new Vector2(0f, 1f);
            topPanel.rectTransform.anchoredPosition = new Vector2(24f, -24f);
            topPanel.rectTransform.sizeDelta = new Vector2(680f, 112f);

            var healthText = CreateText("HealthText", topPanel.transform, 28, FontStyle.Bold);
            Anchor(healthText.rectTransform, new Vector2(0f, 1f), new Vector2(1f, 1f));
            healthText.rectTransform.pivot = new Vector2(0.5f, 1f);
            healthText.rectTransform.offsetMin = new Vector2(22f, -52f);
            healthText.rectTransform.offsetMax = new Vector2(-22f, -12f);

            var collectibleText = CreateText("CollectibleText", topPanel.transform, 22);
            Anchor(collectibleText.rectTransform, new Vector2(0f, 0f), new Vector2(1f, 0f));
            collectibleText.rectTransform.pivot = new Vector2(0.5f, 0f);
            collectibleText.rectTransform.offsetMin = new Vector2(22f, 12f);
            collectibleText.rectTransform.offsetMax = new Vector2(-22f, 52f);

            var statusText = CreateText("FeedbackText", canvasObject.transform, 38, FontStyle.Bold);
            statusText.alignment = TextAnchor.MiddleCenter;
            statusText.color = new Color(1f, 0.9f, 0.35f, 1f);
            Anchor(statusText.rectTransform, new Vector2(0.5f, 1f), new Vector2(0.5f, 1f));
            statusText.rectTransform.pivot = new Vector2(0.5f, 1f);
            statusText.rectTransform.anchoredPosition = new Vector2(0f, -54f);
            statusText.rectTransform.sizeDelta = new Vector2(720f, 70f);

            var damageFlash = CreateImage(
                "DamageFlash",
                canvasObject.transform,
                new Color(1f, 0.05f, 0.05f, 0f)
            );
            Stretch(damageFlash.rectTransform);
            damageFlash.raycastTarget = false;
            damageFlash.transform.SetAsFirstSibling();

            var particles = CreateFeedbackParticles(entityRoot);
            var controller = canvasObject.AddComponent<PrototypePresentationController>();
            controller.Bind(
                player.GetComponent<HealthComponent>(),
                collectibles,
                goal,
                stage,
                sceneCamera.GetComponent<PrototypeCameraFollow>(),
                healthText,
                collectibleText,
                statusText,
                damageFlash,
                particles
            );
            controller.Configure(
                plan.HasCue("player_hit"),
                plan.HasCue("collectible_pickup"),
                plan.HasCue("checkpoint_reached"),
                plan.camera_effects.Contains("hit shake")
            );
            return controller;
        }

        private static UnityEngine.UI.Image CreateImage(string name, Transform parent, Color color)
        {
            var instance = new GameObject(name, typeof(RectTransform));
            instance.transform.SetParent(parent, false);
            var image = instance.AddComponent<UnityEngine.UI.Image>();
            image.color = color;
            return image;
        }

        private static UnityEngine.UI.Text CreateText(
            string name,
            Transform parent,
            int fontSize,
            FontStyle fontStyle = FontStyle.Normal
        )
        {
            var instance = new GameObject(name, typeof(RectTransform));
            instance.transform.SetParent(parent, false);
            var text = instance.AddComponent<UnityEngine.UI.Text>();
            text.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            text.fontSize = fontSize;
            text.fontStyle = fontStyle;
            text.alignment = TextAnchor.MiddleLeft;
            text.color = Color.white;
            text.raycastTarget = false;
            return text;
        }

        private static ParticleSystem CreateFeedbackParticles(Transform parent)
        {
            var instance = new GameObject("FeedbackParticles");
            instance.transform.SetParent(parent, false);
            var particles = instance.AddComponent<ParticleSystem>();
            var main = particles.main;
            main.playOnAwake = false;
            main.loop = false;
            main.duration = 0.6f;
            main.startLifetime = 0.45f;
            main.startSpeed = 2.2f;
            main.startSize = 0.16f;
            main.maxParticles = 64;
            var emission = particles.emission;
            emission.enabled = false;
            particles.Stop(true, ParticleSystemStopBehavior.StopEmittingAndClear);
            return particles;
        }

        private static void Anchor(RectTransform target, Vector2 minimum, Vector2 maximum)
        {
            target.anchorMin = minimum;
            target.anchorMax = maximum;
        }

        private static void Stretch(RectTransform target)
        {
            target.anchorMin = Vector2.zero;
            target.anchorMax = Vector2.one;
            target.offsetMin = Vector2.zero;
            target.offsetMax = Vector2.zero;
        }
    }
}

using System.Collections;
using NUnit.Framework;
using TeamIdle.GameTemplate.Common;
using UnityEngine;
using UnityEngine.TestTools;

namespace TeamIdle.GameTemplate.VisualTests
{
    public sealed class UiArtBindingTests
    {
        [UnityTest]
        public IEnumerator BindsAnImageCreatedAfterTheAssetIsRegistered()
        {
            var host = new GameObject("UiArtBindingHost");
            var binder = host.AddComponent<GeneratedUiArtBinder>();
            var texture = new Texture2D(2, 2);
            var sprite = Sprite.Create(texture, new Rect(0f, 0f, 2f, 2f), Vector2.zero);
            binder.Register("hud_icon_health", "HudIconHealth", sprite);

            var imageObject = new GameObject("HudIconHealthRuntime", typeof(RectTransform));
            var image = imageObject.AddComponent<UnityEngine.UI.Image>();
            yield return null;

            Assert.That(image.sprite, Is.EqualTo(sprite));
            Assert.That(image.raycastTarget, Is.False);

            Object.Destroy(imageObject);
            Object.Destroy(host);
            Object.Destroy(sprite);
            Object.Destroy(texture);
        }
    }
}

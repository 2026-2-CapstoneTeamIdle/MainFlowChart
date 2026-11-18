using System.Collections;
using NUnit.Framework;
using TeamIdle.GameTemplate.Common;
using UnityEngine;
using UnityEngine.TestTools;

namespace TeamIdle.GameTemplate.VisualTests
{
    public sealed class RuntimeSpriteBindingTests
    {
        [UnityTest]
        public IEnumerator BindsSpriteToAnObjectSpawnedAfterImport()
        {
            var host = new GameObject("RuntimeSpriteBindingHost");
            var binder = host.AddComponent<GeneratedRuntimeSpriteBinder>();
            var texture = new Texture2D(2, 2);
            var sprite = Sprite.Create(texture, new Rect(0f, 0f, 2f, 2f), Vector2.zero);
            binder.Register("visual_enemy_fast", "Enemy_Fast_", sprite);
            binder.Register("visual_enemy_fast", "Enemy_Swift_", sprite);

            var enemy = new GameObject("Enemy_Fast_1");
            var art = new GameObject("Art");
            art.transform.SetParent(enemy.transform);
            var renderer = art.AddComponent<SpriteRenderer>();
            renderer.color = Color.magenta;
            var swift = new GameObject("Enemy_Swift_1", typeof(SpriteRenderer));
            var swiftRenderer = swift.GetComponent<SpriteRenderer>();
            yield return null;

            Assert.That(renderer.sprite, Is.EqualTo(sprite));
            Assert.That(renderer.color, Is.EqualTo(Color.white));
            Assert.That(swiftRenderer.sprite, Is.EqualTo(sprite));

            Object.Destroy(enemy);
            Object.Destroy(swift);
            Object.Destroy(host);
            Object.Destroy(sprite);
            Object.Destroy(texture);
        }

        [UnityTest]
        public IEnumerator PrefersTheMostSpecificEnemyPrefix()
        {
            var host = new GameObject("RuntimeSpriteBindingHost");
            var binder = host.AddComponent<GeneratedRuntimeSpriteBinder>();
            var texture = new Texture2D(4, 2);
            var generic = Sprite.Create(texture, new Rect(0f, 0f, 2f, 2f), Vector2.zero);
            var fast = Sprite.Create(texture, new Rect(2f, 0f, 2f, 2f), Vector2.zero);
            binder.Register("enemy_sprite", "Enemy_", generic);
            binder.Register("enemy_fast_sprite", "Enemy_Fast_", fast);

            var enemy = new GameObject("Enemy_Fast_1");
            var art = new GameObject("Art");
            art.transform.SetParent(enemy.transform);
            var renderer = art.AddComponent<SpriteRenderer>();
            yield return null;

            Assert.That(renderer.sprite, Is.EqualTo(fast));
            Object.Destroy(enemy);
            Object.Destroy(host);
            Object.Destroy(generic);
            Object.Destroy(fast);
            Object.Destroy(texture);
        }
    }
}

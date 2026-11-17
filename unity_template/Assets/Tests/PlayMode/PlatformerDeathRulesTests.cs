using NUnit.Framework;
using TeamIdle.GameTemplate.Common;
using TeamIdle.GameTemplate.Prototype;
using UnityEngine;

namespace TeamIdle.GameTemplate.VisualTests
{
    public sealed class PlatformerDeathRulesTests
    {
        [Test]
        public void DefaultLethalDamageRaisesDefeatWithoutRespawning()
        {
            var player = new GameObject("Player", typeof(HealthComponent));
            var health = player.GetComponent<HealthComponent>();
            health.SetMaximum(3f);
            var stage = new GameObject("Stage").AddComponent<PrototypePlatformerStageController>();
            stage.Bind(player.transform);
            var damageSystem = new GameObject(
                "DamageSystem"
            ).AddComponent<HealthDamageSystemModule>();
            damageSystem.BindPlayer(health);
            player.transform.position = Vector3.right * 3f;
            var deathCount = 0;
            var defeatCount = 0;
            health.Died += () => deathCount++;
            damageSystem.PlayerDefeated += () => defeatCount++;

            health.Damage(3f);

            Assert.That(deathCount, Is.EqualTo(1));
            Assert.That(defeatCount, Is.EqualTo(1));
            Assert.That(damageSystem.IsGameOver, Is.True);
            Assert.That(health.Current, Is.EqualTo(0f));
            Assert.That(player.transform.position.x, Is.EqualTo(3f));
            Object.DestroyImmediate(damageSystem.gameObject);
            Object.DestroyImmediate(stage.gameObject);
            Object.DestroyImmediate(player);
        }

        [Test]
        public void RequestedCheckpointRecoveryRestoresPlayer()
        {
            var player = new GameObject("Player", typeof(HealthComponent));
            var health = player.GetComponent<HealthComponent>();
            health.SetMaximum(3f);
            var stage = new GameObject("Stage").AddComponent<PrototypePlatformerStageController>();
            stage.Bind(player.transform);
            stage.ConfigureDeathRecovery(true);
            var damageSystem = new GameObject(
                "DamageSystem"
            ).AddComponent<HealthDamageSystemModule>();
            damageSystem.BindPlayer(health);
            player.transform.position = Vector3.right * 3f;

            health.Damage(3f);

            Assert.That(health.Current, Is.EqualTo(3f));
            Assert.That(player.transform.position, Is.EqualTo(Vector3.zero));
            Assert.That(damageSystem.IsGameOver, Is.False);
            Object.DestroyImmediate(damageSystem.gameObject);
            Object.DestroyImmediate(stage.gameObject);
            Object.DestroyImmediate(player);
        }
    }
}

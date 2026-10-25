using System;
using TeamIdle.GameTemplate.Core;
using UnityEngine;

namespace TeamIdle.GameTemplate.Common
{
    public sealed class HealthDamageSystemModule : GameModuleBehaviour
    {
        public override string ModuleId => "health_damage_system";
        public HealthComponent PlayerHealth { get; private set; }
        public bool IsGameOver { get; private set; }
        public event Action<HealthComponent, float> Damaged;
        public event Action PlayerDefeated;

        public void ApplyDamage(HealthComponent target, float amount)
        {
            if (target == null || amount <= 0f)
                return;
            target.Damage(amount);
            Damaged?.Invoke(target, amount);
        }

        public void BindPlayer(HealthComponent health)
        {
            if (PlayerHealth != null)
                PlayerHealth.Died -= HandlePlayerDied;
            PlayerHealth = health;
            IsGameOver = PlayerHealth != null && !PlayerHealth.IsAlive;
            if (PlayerHealth != null)
                PlayerHealth.Died += HandlePlayerDied;
        }

        protected override void OnInitialize(GameContext context)
        {
            var player = GameObject.Find("Player");
            if (player != null)
                BindPlayer(player.GetComponent<HealthComponent>());
            context.Register(this);
        }

        protected override void OnShutdown()
        {
            if (PlayerHealth != null)
                PlayerHealth.Died -= HandlePlayerDied;
        }

        private void HandlePlayerDied()
        {
            if (IsGameOver)
                return;
            IsGameOver = true;
            PlayerDefeated?.Invoke();
        }
    }
}

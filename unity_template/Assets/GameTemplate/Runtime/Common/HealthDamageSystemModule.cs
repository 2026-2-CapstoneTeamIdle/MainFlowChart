using System;
using TeamIdle.GameTemplate.Core;

namespace TeamIdle.GameTemplate.Common
{
    public sealed class HealthDamageSystemModule : GameModuleBehaviour
    {
        public override string ModuleId => "health_damage_system";
        public event Action<HealthComponent, float> Damaged;

        public void ApplyDamage(HealthComponent target, float amount)
        {
            if (target == null || amount <= 0f)
                return;
            target.Damage(amount);
            Damaged?.Invoke(target, amount);
        }

        protected override void OnInitialize(GameContext context) => context.Register(this);
    }
}

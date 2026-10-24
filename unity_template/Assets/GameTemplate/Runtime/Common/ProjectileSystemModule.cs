using TeamIdle.GameTemplate.Core;
using UnityEngine;

namespace TeamIdle.GameTemplate.Common
{
    public sealed class ProjectileSystemModule : GameModuleBehaviour
    {
        public override string ModuleId => "projectile_system";

        public Projectile2D Spawn(
            Projectile2D prefab,
            Vector2 position,
            Vector2 direction,
            float damage,
            float speed,
            float lifetime = 5f
        )
        {
            if (prefab == null)
            {
                return null;
            }

            var projectile = Instantiate(prefab, position, Quaternion.identity);
            projectile.Launch(direction, damage, speed, lifetime);
            return projectile;
        }

        protected override void OnInitialize(GameContext context)
        {
            context.Register(this);
        }
    }
}

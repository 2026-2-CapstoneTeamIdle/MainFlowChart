using TeamIdle.GameTemplate.Common;
using TeamIdle.GameTemplate.Core;
using UnityEngine;

namespace TeamIdle.GameTemplate.TowerDefense
{
    public sealed class TowerTargetingSystemModule : GameModuleBehaviour
    {
        [SerializeField]
        private Projectile2D projectilePrefab;

        [SerializeField]
        private LayerMask enemyMask;

        [SerializeField]
        private float range = 4f;

        [SerializeField]
        private float attacksPerSecond = 1f;

        [SerializeField]
        private float damage = 10f;
        private ProjectileSystemModule projectiles;
        private float nextAttackTime;
        public override string ModuleId => "tower_targeting_system";

        protected override void OnInitialize(GameContext context)
        {
            projectiles = context.GetRequired<ProjectileSystemModule>();
            context.Register(this);
        }

        private void Update()
        {
            if (!IsInitialized || Time.time < nextAttackTime || projectilePrefab == null)
                return;
            var target = FindNearestTarget();
            if (target == null)
                return;
            var direction = ((Vector2)target.position - (Vector2)transform.position).normalized;
            projectiles.Spawn(projectilePrefab, transform.position, direction, damage, 10f);
            nextAttackTime = Time.time + 1f / Mathf.Max(0.01f, attacksPerSecond);
        }

        private Transform FindNearestTarget()
        {
            var hits = Physics2D.OverlapCircleAll(transform.position, range, enemyMask);
            Transform nearest = null;
            var nearestDistance = float.PositiveInfinity;
            foreach (var hit in hits)
            {
                var distance = (
                    (Vector2)hit.transform.position - (Vector2)transform.position
                ).sqrMagnitude;
                if (distance < nearestDistance)
                {
                    nearest = hit.transform;
                    nearestDistance = distance;
                }
            }
            return nearest;
        }
    }
}

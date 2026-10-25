using TeamIdle.GameTemplate.Common;
using TeamIdle.GameTemplate.Core;
using UnityEngine;

namespace TeamIdle.GameTemplate.SurvivorLike
{
    public sealed class AutoTargetSystemModule : GameModuleBehaviour
    {
        [SerializeField]
        private Transform origin;

        [SerializeField]
        private Projectile2D projectilePrefab;

        [SerializeField]
        private LayerMask enemyMask;

        [SerializeField]
        private float range = 8f;

        [SerializeField]
        private float attacksPerSecond = 1f;

        [SerializeField]
        private float damage = 10f;

        [SerializeField]
        private int projectileCount = 1;

        private ProjectileSystemModule projectiles;
        private float nextAttackTime;

        public override string ModuleId => "auto_target_system";

        public float Damage
        {
            get => damage;
            set => damage = Mathf.Max(0f, value);
        }

        public float AttacksPerSecond
        {
            get => attacksPerSecond;
            set => attacksPerSecond = Mathf.Max(0.01f, value);
        }

        public int ProjectileCount
        {
            get => projectileCount;
            set => projectileCount = Mathf.Max(1, value);
        }

        protected override void OnInitialize(GameContext context)
        {
            projectiles = context.GetRequired<ProjectileSystemModule>();
            origin ??= transform;
            context.Register(this);
        }

        private void Update()
        {
            if (!IsInitialized || projectilePrefab == null || Time.time < nextAttackTime)
            {
                return;
            }

            var target = FindNearest();
            if (target == null)
            {
                return;
            }

            var baseDirection = ((Vector2)target.position - (Vector2)origin.position).normalized;
            var spread = Mathf.Min(45f, 8f * (projectileCount - 1));
            for (var index = 0; index < projectileCount; index++)
            {
                var t = projectileCount == 1 ? 0.5f : index / (float)(projectileCount - 1);
                var angle = Mathf.Lerp(-spread * 0.5f, spread * 0.5f, t);
                var direction = Quaternion.Euler(0f, 0f, angle) * baseDirection;
                projectiles.Spawn(projectilePrefab, origin.position, direction, damage, 12f);
            }

            nextAttackTime = Time.time + 1f / attacksPerSecond;
        }

        private Transform FindNearest()
        {
            var hits = Physics2D.OverlapCircleAll(origin.position, range, enemyMask);
            Transform nearest = null;
            var nearestDistance = float.PositiveInfinity;
            foreach (var hit in hits)
            {
                var distance = (
                    (Vector2)hit.transform.position - (Vector2)origin.position
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

using TeamIdle.GameTemplate.Common;
using UnityEngine;

namespace TeamIdle.GameTemplate.Prototype
{
    public sealed class PrototypeTowerWeapon : MonoBehaviour
    {
        private Projectile2D projectilePrefab;
        private ProjectileSystemModule projectiles;
        private float nextAttackTime;
        private float range = 4f;
        private float attacksPerSecond = 1.2f;
        private float damage = 12f;

        public string TowerTypeId { get; private set; } = "basic";
        public int Level { get; private set; } = 1;
        public float Range => range;
        public float AttacksPerSecond => attacksPerSecond;
        public float Damage => damage;

        public void Configure(Projectile2D prefab)
        {
            Configure(prefab, "basic", 4f, 1.2f, 12f);
        }

        public void Configure(
            Projectile2D prefab,
            string towerTypeId,
            float attackRange,
            float attackRate,
            float attackDamage
        )
        {
            projectilePrefab = prefab;
            TowerTypeId = string.IsNullOrWhiteSpace(towerTypeId) ? "basic" : towerTypeId;
            range = Mathf.Max(0.1f, attackRange);
            attacksPerSecond = Mathf.Max(0.1f, attackRate);
            damage = Mathf.Max(0.1f, attackDamage);
            Level = 1;
        }

        public void Upgrade(float damageMultiplier, float rateMultiplier, float rangeBonus)
        {
            damage *= Mathf.Max(1f, damageMultiplier);
            attacksPerSecond *= Mathf.Max(1f, rateMultiplier);
            range += Mathf.Max(0f, rangeBonus);
            Level++;
        }

        private void Start()
        {
            projectiles = FindFirstObjectByType<ProjectileSystemModule>();
        }

        private void Update()
        {
            if (projectiles == null || projectilePrefab == null || Time.time < nextAttackTime)
            {
                return;
            }

            var target = FindNearestEnemy();
            if (target == null)
            {
                return;
            }

            var direction = ((Vector2)target.position - (Vector2)transform.position).normalized;
            projectiles.Spawn(projectilePrefab, transform.position, direction, damage, 10f);
            nextAttackTime = Time.time + 1f / attacksPerSecond;
        }

        private Transform FindNearestEnemy()
        {
            Transform nearest = null;
            var nearestDistance = range * range;
            foreach (var health in FindObjectsByType<HealthComponent>(FindObjectsSortMode.None))
            {
                if (health.gameObject.layer != 8 || !health.IsAlive)
                {
                    continue;
                }

                var distance = (
                    (Vector2)health.transform.position - (Vector2)transform.position
                ).sqrMagnitude;
                if (distance <= nearestDistance)
                {
                    nearest = health.transform;
                    nearestDistance = distance;
                }
            }

            return nearest;
        }
    }
}

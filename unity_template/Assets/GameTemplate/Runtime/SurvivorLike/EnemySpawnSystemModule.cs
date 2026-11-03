using System.Collections;
using System.Collections.Generic;
using TeamIdle.GameTemplate.Common;
using TeamIdle.GameTemplate.Core;
using UnityEngine;

namespace TeamIdle.GameTemplate.SurvivorLike
{
    public sealed class EnemySpawnSystemModule : GameModuleBehaviour
    {
        [SerializeField]
        private ChaseAgent2D enemyPrefab;

        [SerializeField]
        private Transform target;

        [SerializeField]
        private float spawnRadius = 10f;

        [SerializeField]
        private float spawnInterval = 1f;

        [SerializeField]
        private int maximumAlive = 50;
        private readonly List<ChaseAgent2D> spawned = new();
        public override string ModuleId => "enemy_spawn_system";
        public int AliveCount
        {
            get
            {
                spawned.RemoveAll(enemy => enemy == null);
                return spawned.Count;
            }
        }
        public IReadOnlyList<ChaseAgent2D> SpawnedEnemies => spawned;
        public float SpawnInterval => spawnInterval;
        public int MaximumAlive => maximumAlive;

        public void ConfigureDifficulty(float nextSpawnInterval, int nextMaximumAlive)
        {
            spawnInterval = Mathf.Max(0.05f, nextSpawnInterval);
            maximumAlive = Mathf.Max(1, nextMaximumAlive);
        }

        public ChaseAgent2D SpawnAt(Vector2 position, float healthMultiplier = 1f)
        {
            if (enemyPrefab == null || target == null)
                return null;
            var enemy = Instantiate(enemyPrefab, position, Quaternion.identity);
            enemy.SetTarget(target);
            var health = enemy.GetComponent<HealthComponent>();
            if (health != null)
                health.SetMaximum(health.Maximum * Mathf.Max(0.01f, healthMultiplier));
            spawned.Add(enemy);
            return enemy;
        }

        protected override void OnInitialize(GameContext context)
        {
            context.Register(this);
            StartCoroutine(SpawnLoop());
        }

        protected override void OnShutdown()
        {
            StopAllCoroutines();
            spawned.Clear();
        }

        private IEnumerator SpawnLoop()
        {
            while (true)
            {
                spawned.RemoveAll(enemy => enemy == null);
                if (enemyPrefab != null && target != null && spawned.Count < maximumAlive)
                {
                    var direction = Random.insideUnitCircle.normalized;
                    if (direction.sqrMagnitude < 0.01f)
                        direction = Vector2.right;
                    SpawnAt((Vector2)target.position + direction * spawnRadius);
                }
                yield return new WaitForSeconds(Mathf.Max(0.05f, spawnInterval));
            }
        }
    }
}

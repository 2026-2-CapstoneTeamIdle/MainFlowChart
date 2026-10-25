using System.Collections;
using System.Collections.Generic;
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
                    var enemy = Instantiate(
                        enemyPrefab,
                        (Vector2)target.position + direction * spawnRadius,
                        Quaternion.identity
                    );
                    enemy.SetTarget(target);
                    spawned.Add(enemy);
                }
                yield return new WaitForSeconds(Mathf.Max(0.05f, spawnInterval));
            }
        }
    }
}

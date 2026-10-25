#if false // Compatibility shell: MonoBehaviours were moved to filename-matched scripts.
using System;
using System.Collections;
using System.Collections.Generic;
using TeamIdle.GameTemplate.Common;
using TeamIdle.GameTemplate.Core;
using UnityEngine;

namespace TeamIdle.GameTemplate.TowerDefense
{
    public sealed class PathFollower2D : MonoBehaviour
    {
        [SerializeField]
        private float speed = 2f;

        private IReadOnlyList<Transform> waypoints;
        private int waypointIndex;

        public event Action ReachedEnd;

        public void SetPath(IReadOnlyList<Transform> nextWaypoints)
        {
            waypoints = nextWaypoints;
            waypointIndex = 0;
        }

        private void Update()
        {
            if (waypoints == null || waypointIndex >= waypoints.Count)
            {
                return;
            }

            var destination = waypoints[waypointIndex];
            if (destination == null)
            {
                waypointIndex++;
                return;
            }

            transform.position = Vector3.MoveTowards(
                transform.position,
                destination.position,
                speed * Time.deltaTime
            );
            if ((transform.position - destination.position).sqrMagnitude > 0.001f)
            {
                return;
            }

            waypointIndex++;
            if (waypointIndex >= waypoints.Count)
            {
                ReachedEnd?.Invoke();
            }
        }
    }

    public sealed class WaveSpawnerModule : GameModuleBehaviour
    {
        [SerializeField]
        private PathFollower2D enemyPrefab;

        [SerializeField]
        private Transform spawnPoint;

        [SerializeField]
        private List<Transform> waypoints = new();

        [SerializeField]
        private int baseEnemyCount = 5;

        [SerializeField]
        private float spawnInterval = 0.5f;

        [SerializeField]
        private bool autoStartFirstWave = true;

        [SerializeField]
        private float initialDelay = 1.5f;

        private bool waveRunning;

        public override string ModuleId => "wave_spawner";

        public int WaveNumber { get; private set; }

        public bool IsWaveRunning => waveRunning;

        public event Action<int> WaveStarted;

        public event Action<int> WaveSpawnCompleted;

        public bool StartNextWave()
        {
            if (!IsInitialized || waveRunning || enemyPrefab == null || spawnPoint == null)
            {
                return false;
            }

            StartCoroutine(SpawnWave());
            return true;
        }

        protected override void OnInitialize(GameContext context)
        {
            context.Register(this);
            if (autoStartFirstWave)
            {
                StartCoroutine(StartFirstWaveAfterDelay());
            }
        }

        private IEnumerator StartFirstWaveAfterDelay()
        {
            yield return new WaitForSeconds(Mathf.Max(0f, initialDelay));
            StartNextWave();
        }

        private IEnumerator SpawnWave()
        {
            waveRunning = true;
            WaveNumber++;
            WaveStarted?.Invoke(WaveNumber);
            var count = baseEnemyCount + WaveNumber - 1;
            for (var index = 0; index < count; index++)
            {
                var enemy = Instantiate(enemyPrefab, spawnPoint.position, Quaternion.identity);
                enemy.SetPath(waypoints);
                yield return new WaitForSeconds(spawnInterval);
            }

            waveRunning = false;
            WaveSpawnCompleted?.Invoke(WaveNumber);
        }
    }

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
            {
                return;
            }

            var target = FindNearestTarget();
            if (target == null)
            {
                return;
            }

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

    public sealed class BaseDefenseSystemModule : GameModuleBehaviour
    {
        [SerializeField]
        private int startingLives = 20;

        public override string ModuleId => "base_defense_system";

        public int Lives { get; private set; }

        public event Action<int> LivesChanged;

        public event Action Defeated;

        public void LoseLives(int amount = 1)
        {
            Lives = Mathf.Max(0, Lives - Mathf.Max(0, amount));
            LivesChanged?.Invoke(Lives);
            if (Lives == 0)
            {
                Defeated?.Invoke();
            }
        }

        protected override void OnInitialize(GameContext context)
        {
            Lives = Mathf.Max(1, startingLives);
            context.Register(this);
        }
    }
}
#endif

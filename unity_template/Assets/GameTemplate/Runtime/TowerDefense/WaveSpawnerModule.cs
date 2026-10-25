using System;
using System.Collections;
using System.Collections.Generic;
using TeamIdle.GameTemplate.Core;
using UnityEngine;

namespace TeamIdle.GameTemplate.TowerDefense
{
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
                return false;
            StartCoroutine(SpawnWave());
            return true;
        }

        protected override void OnInitialize(GameContext context)
        {
            context.Register(this);
            if (autoStartFirstWave)
                StartCoroutine(StartFirstWaveAfterDelay());
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
}

using System;
using System.Collections;
using System.Collections.Generic;
using TeamIdle.GameTemplate.Common;
using TeamIdle.GameTemplate.Core;
using UnityEngine;

namespace TeamIdle.GameTemplate.SurvivorLike
{
    public sealed class TopDownMovementModule : GameModuleBehaviour
    {
        [SerializeField]
        private Rigidbody2D target;

        [SerializeField]
        private float moveSpeed = 5f;

        private InputAdapterModule input;

        public override string ModuleId => "top_down_movement";

        public float MoveSpeed
        {
            get => moveSpeed;
            set => moveSpeed = Mathf.Max(0f, value);
        }

        public void Bind(Rigidbody2D body)
        {
            target = body;
        }

        protected override void OnInitialize(GameContext context)
        {
            input = context.GetRequired<InputAdapterModule>();
            context.Register(this);
        }

        private void FixedUpdate()
        {
            if (IsInitialized && target != null)
            {
                target.linearVelocity = input.Movement.normalized * moveSpeed;
            }
        }
    }

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
                    var direction = UnityEngine.Random.insideUnitCircle.normalized;
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

    public sealed class ExperienceSystemModule : GameModuleBehaviour
    {
        [SerializeField]
        private int baseRequiredExperience = 10;

        [SerializeField]
        private float requirementGrowth = 1.25f;

        public override string ModuleId => "experience_system";

        public int Level { get; private set; }

        public int Experience { get; private set; }

        public int RequiredExperience { get; private set; }

        public event Action<int> LevelGained;

        public event Action<int, int> ExperienceChanged;

        public void Add(int amount)
        {
            Experience += Mathf.Max(0, amount);
            while (Experience >= RequiredExperience)
            {
                Experience -= RequiredExperience;
                Level++;
                RequiredExperience = Mathf.Max(
                    RequiredExperience + 1,
                    Mathf.RoundToInt(RequiredExperience * requirementGrowth)
                );
                LevelGained?.Invoke(Level);
            }

            ExperienceChanged?.Invoke(Experience, RequiredExperience);
        }

        protected override void OnInitialize(GameContext context)
        {
            Level = 1;
            RequiredExperience = Mathf.Max(1, baseRequiredExperience);
            context.Register(this);
        }
    }

    public enum UpgradeRarity
    {
        Common,
        Rare,
        Epic,
        Legendary,
    }

    public sealed class RaritySystemModule : GameModuleBehaviour
    {
        [SerializeField]
        private Vector4 weights = new(70f, 22f, 7f, 1f);

        public override string ModuleId => "rarity_system";

        public UpgradeRarity Roll()
        {
            var total =
                Mathf.Max(0f, weights.x)
                + Mathf.Max(0f, weights.y)
                + Mathf.Max(0f, weights.z)
                + Mathf.Max(0f, weights.w);
            var roll = UnityEngine.Random.Range(0f, total);
            if ((roll -= Mathf.Max(0f, weights.x)) < 0f)
            {
                return UpgradeRarity.Common;
            }

            if ((roll -= Mathf.Max(0f, weights.y)) < 0f)
            {
                return UpgradeRarity.Rare;
            }

            if ((roll -= Mathf.Max(0f, weights.z)) < 0f)
            {
                return UpgradeRarity.Epic;
            }

            return UpgradeRarity.Legendary;
        }

        protected override void OnInitialize(GameContext context)
        {
            context.Register(this);
        }
    }

    [Serializable]
    public sealed class UpgradeDefinition
    {
        public string upgradeId = string.Empty;
        public string displayName = string.Empty;

        [TextArea]
        public string description = string.Empty;
    }
}

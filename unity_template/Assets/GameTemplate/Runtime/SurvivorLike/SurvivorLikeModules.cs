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

    public sealed class ChaseAgent2D : MonoBehaviour
    {
        [SerializeField]
        private Transform target;

        [SerializeField]
        private float speed = 2f;

        public void SetTarget(Transform nextTarget)
        {
            target = nextTarget;
        }

        private void Update()
        {
            if (target != null)
            {
                transform.position = Vector3.MoveTowards(
                    transform.position,
                    target.position,
                    speed * Time.deltaTime
                );
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

    public sealed class UpgradeSelectionSystemModule : GameModuleBehaviour
    {
        public sealed class UpgradeChoice
        {
            public UpgradeDefinition Upgrade { get; set; }
            public UpgradeRarity Rarity { get; set; }
        }

        [SerializeField]
        private List<UpgradeDefinition> upgradePool = new();

        [SerializeField]
        private int choiceCount = 3;

        private readonly List<UpgradeChoice> currentChoices = new();
        private ExperienceSystemModule experience;
        private RaritySystemModule rarity;

        public override string ModuleId => "upgrade_selection_system";

        public IReadOnlyList<UpgradeChoice> CurrentChoices => currentChoices;

        public event Action<IReadOnlyList<UpgradeChoice>> ChoicesPresented;

        public event Action<UpgradeChoice> Selected;

        public bool Select(int index)
        {
            if (index < 0 || index >= currentChoices.Count)
            {
                return false;
            }

            var choice = currentChoices[index];
            currentChoices.Clear();
            Selected?.Invoke(choice);
            return true;
        }

        protected override void OnInitialize(GameContext context)
        {
            experience = context.GetRequired<ExperienceSystemModule>();
            rarity = context.GetRequired<RaritySystemModule>();
            experience.LevelGained += OnLevelGained;
            context.Register(this);
        }

        protected override void OnShutdown()
        {
            if (experience != null)
            {
                experience.LevelGained -= OnLevelGained;
            }
        }

        private void OnLevelGained(int _)
        {
            currentChoices.Clear();
            var candidates = new List<UpgradeDefinition>(upgradePool);
            var count = Mathf.Min(Mathf.Max(1, choiceCount), candidates.Count);
            for (var index = 0; index < count; index++)
            {
                var candidateIndex = UnityEngine.Random.Range(0, candidates.Count);
                currentChoices.Add(
                    new UpgradeChoice
                    {
                        Upgrade = candidates[candidateIndex],
                        Rarity = rarity.Roll(),
                    }
                );
                candidates.RemoveAt(candidateIndex);
            }

            ChoicesPresented?.Invoke(currentChoices);
        }
    }
}

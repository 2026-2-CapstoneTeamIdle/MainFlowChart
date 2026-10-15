using System;
using TeamIdle.GameTemplate.Core;
using UnityEngine;

namespace TeamIdle.GameTemplate.Common
{
    public sealed class HealthComponent : MonoBehaviour
    {
        [SerializeField]
        private float maximum = 100f;

        [SerializeField]
        private bool destroyOnDeath;

        public float Current { get; private set; }

        public float Maximum => maximum;

        public bool IsAlive => Current > 0f;

        public event Action<float, float> Changed;

        public event Action Died;

        private void Awake()
        {
            Current = Mathf.Max(1f, maximum);
        }

        public void SetMaximum(float value, bool refill = true)
        {
            maximum = Mathf.Max(1f, value);
            Current = refill ? maximum : Mathf.Min(Current, maximum);
            Changed?.Invoke(Current, maximum);
        }

        public void Damage(float amount)
        {
            if (!IsAlive || amount <= 0f)
            {
                return;
            }

            Current = Mathf.Max(0f, Current - amount);
            Changed?.Invoke(Current, maximum);
            if (Current > 0f)
            {
                return;
            }

            Died?.Invoke();
            if (destroyOnDeath)
            {
                Destroy(gameObject);
            }
        }

        public void Heal(float amount)
        {
            if (amount <= 0f || !IsAlive)
            {
                return;
            }

            Current = Mathf.Min(maximum, Current + amount);
            Changed?.Invoke(Current, maximum);
        }
    }

    public sealed class HealthDamageSystemModule : GameModuleBehaviour
    {
        public override string ModuleId => "health_damage_system";

        public event Action<HealthComponent, float> Damaged;

        public void ApplyDamage(HealthComponent target, float amount)
        {
            if (target == null || amount <= 0f)
            {
                return;
            }

            target.Damage(amount);
            Damaged?.Invoke(target, amount);
        }

        protected override void OnInitialize(GameContext context)
        {
            context.Register(this);
        }
    }

    public sealed class Projectile2D : MonoBehaviour
    {
        private Vector2 direction = Vector2.right;
        private float damage = 1f;
        private float speed = 8f;

        public void Launch(Vector2 nextDirection, float nextDamage, float nextSpeed, float lifetime)
        {
            direction = nextDirection.sqrMagnitude > 0f ? nextDirection.normalized : Vector2.right;
            damage = Mathf.Max(0f, nextDamage);
            speed = Mathf.Max(0f, nextSpeed);
            Destroy(gameObject, Mathf.Max(0.05f, lifetime));
        }

        private void Update()
        {
            transform.position += (Vector3)(direction * (speed * Time.deltaTime));
        }

        private void OnTriggerEnter2D(Collider2D other)
        {
            if (other.TryGetComponent<HealthComponent>(out var health))
            {
                health.Damage(damage);
                Destroy(gameObject);
            }
        }
    }

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

    public sealed class EconomySystemModule : GameModuleBehaviour
    {
        [SerializeField]
        private int startingCurrency;

        public override string ModuleId => "economy_system";

        public int Currency { get; private set; }

        public event Action<int> Changed;

        public void Add(int amount)
        {
            Currency = Mathf.Max(0, Currency + amount);
            Changed?.Invoke(Currency);
        }

        public bool Spend(int amount)
        {
            if (amount < 0 || Currency < amount)
            {
                return false;
            }

            Currency -= amount;
            Changed?.Invoke(Currency);
            return true;
        }

        protected override void OnInitialize(GameContext context)
        {
            Currency = Mathf.Max(0, startingCurrency);
            context.Register(this);
        }
    }
}

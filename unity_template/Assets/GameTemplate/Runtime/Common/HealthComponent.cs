using System;
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

        private void Awake() => Current = Mathf.Max(1f, maximum);

        public void SetMaximum(float value, bool refill = true)
        {
            maximum = Mathf.Max(1f, value);
            Current = refill ? maximum : Mathf.Min(Current, maximum);
            Changed?.Invoke(Current, maximum);
        }

        public void Damage(float amount)
        {
            if (!IsAlive || amount <= 0f)
                return;
            Current = Mathf.Max(0f, Current - amount);
            Changed?.Invoke(Current, maximum);
            if (Current > 0f)
                return;
            Died?.Invoke();
            if (destroyOnDeath)
                Destroy(gameObject);
        }

        public void Heal(float amount)
        {
            if (amount <= 0f || !IsAlive)
                return;
            Current = Mathf.Min(maximum, Current + amount);
            Changed?.Invoke(Current, maximum);
        }
    }
}

using TeamIdle.GameTemplate.Common;
using UnityEngine;

namespace TeamIdle.GameTemplate.Prototype
{
    public sealed class PrototypeHazard : MonoBehaviour
    {
        [SerializeField]
        private string archetype = string.Empty;

        [SerializeField]
        private float damage = 25f;

        public float Damage => damage;

        public string Archetype => archetype;

        public void Configure(string nextArchetype, float nextDamage)
        {
            archetype = nextArchetype ?? string.Empty;
            damage = Mathf.Max(0f, nextDamage);
        }

        private void OnTriggerEnter2D(Collider2D other)
        {
            if (!other.CompareTag("Player"))
            {
                return;
            }

            other.GetComponent<HealthComponent>()?.Damage(damage);
            FindFirstObjectByType<PrototypePlatformerStageController>()?.Respawn();
        }
    }
}

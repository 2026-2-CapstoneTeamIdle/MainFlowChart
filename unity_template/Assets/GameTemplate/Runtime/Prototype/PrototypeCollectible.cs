using TeamIdle.GameTemplate.Platformer;
using UnityEngine;

namespace TeamIdle.GameTemplate.Prototype
{
    public sealed class PrototypeCollectible : MonoBehaviour
    {
        [SerializeField]
        private string archetype = string.Empty;

        [SerializeField]
        private int amount = 1;

        public int Amount => amount;

        public string Archetype => archetype;

        public void Configure(string nextArchetype, int nextAmount)
        {
            archetype = nextArchetype ?? string.Empty;
            amount = Mathf.Max(1, nextAmount);
        }

        private void OnTriggerEnter2D(Collider2D other)
        {
            if (!other.CompareTag("Player"))
            {
                return;
            }

            FindFirstObjectByType<CollectibleSystemModule>()?.Collect(amount);
            Destroy(gameObject);
        }
    }
}

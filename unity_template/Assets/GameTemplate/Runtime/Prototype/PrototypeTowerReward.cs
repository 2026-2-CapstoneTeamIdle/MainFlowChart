using TeamIdle.GameTemplate.Common;
using UnityEngine;

namespace TeamIdle.GameTemplate.Prototype
{
    public sealed class PrototypeTowerReward : MonoBehaviour
    {
        [SerializeField]
        private int amount = 10;

        private HealthComponent health;

        private void Awake()
        {
            health = GetComponent<HealthComponent>();
            if (health != null)
            {
                health.Died += Grant;
            }
        }

        private void OnDestroy()
        {
            if (health != null)
            {
                health.Died -= Grant;
            }
        }

        private void Grant()
        {
            FindFirstObjectByType<EconomySystemModule>()?.Add(amount);
        }
    }
}

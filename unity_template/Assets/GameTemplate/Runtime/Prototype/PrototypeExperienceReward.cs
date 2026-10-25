using TeamIdle.GameTemplate.Common;
using TeamIdle.GameTemplate.SurvivorLike;
using UnityEngine;

namespace TeamIdle.GameTemplate.Prototype
{
    public sealed class PrototypeExperienceReward : MonoBehaviour
    {
        [SerializeField]
        private int amount = 2;

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
            FindFirstObjectByType<ExperienceSystemModule>()?.Add(amount);
        }
    }
}

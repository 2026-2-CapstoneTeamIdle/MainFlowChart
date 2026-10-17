using TeamIdle.GameTemplate.Platformer;
using UnityEngine;

namespace TeamIdle.GameTemplate.Prototype
{
    public sealed class PrototypeGoal : MonoBehaviour
    {
        private void OnTriggerEnter2D(Collider2D other)
        {
            if (other.CompareTag("Player"))
            {
                FindFirstObjectByType<GoalSystemModule>()?.TryComplete();
            }
        }
    }
}

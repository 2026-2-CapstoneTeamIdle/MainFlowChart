using UnityEngine;

namespace TeamIdle.GameTemplate.Prototype
{
    public sealed class PrototypeCheckpoint : MonoBehaviour
    {
        [SerializeField]
        private int checkpointIndex;

        public int CheckpointIndex => checkpointIndex;

        public void Configure(int index)
        {
            checkpointIndex = index;
        }

        private void OnTriggerEnter2D(Collider2D other)
        {
            if (other.CompareTag("Player"))
            {
                FindFirstObjectByType<PrototypePlatformerStageController>()
                    ?.ActivateCheckpoint(checkpointIndex, transform.position);
            }
        }
    }
}

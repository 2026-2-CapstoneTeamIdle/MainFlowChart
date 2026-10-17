using System;
using UnityEngine;

namespace TeamIdle.GameTemplate.Prototype
{
    public sealed class PrototypePlatformerStageController : MonoBehaviour
    {
        [SerializeField]
        private Transform player;

        [SerializeField]
        private float fallLimit = -7f;

        private Vector3 checkpoint;

        public event Action<int, Vector3> CheckpointActivated;

        public int CheckpointIndex { get; private set; }

        public Vector3 CurrentCheckpoint => checkpoint;

        public void Bind(Transform nextPlayer)
        {
            player = nextPlayer;
            checkpoint = player == null ? Vector3.zero : player.position;
        }

        public void ActivateCheckpoint(int index, Vector3 position)
        {
            if (index <= CheckpointIndex)
            {
                return;
            }

            CheckpointIndex = index;
            checkpoint = position;
            CheckpointActivated?.Invoke(index, position);
        }

        public void Respawn()
        {
            if (player == null)
            {
                return;
            }

            player.position = checkpoint;
            if (player.TryGetComponent<Rigidbody2D>(out var body))
            {
                body.linearVelocity = Vector2.zero;
            }
        }

        private void Update()
        {
            if (player != null && player.position.y < fallLimit)
            {
                Respawn();
            }
        }
    }
}

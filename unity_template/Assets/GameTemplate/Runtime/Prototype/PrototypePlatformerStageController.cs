using System;
using TeamIdle.GameTemplate.Common;
using TeamIdle.GameTemplate.Core;
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
        private HealthComponent playerHealth;

        [SerializeField]
        private bool respawnOnDeath;

        public event Action<int, Vector3> CheckpointActivated;

        public int CheckpointIndex { get; private set; }

        public Vector3 CurrentCheckpoint => checkpoint;

        public bool RespawnOnDeath => respawnOnDeath;

        private void OnEnable()
        {
            if (Application.isPlaying)
            {
                Bind(player);
            }
        }

        private void OnDisable()
        {
            if (playerHealth != null)
            {
                playerHealth.Changed -= HandleHealthChanged;
            }
        }

        public void ConfigureDeathRecovery(bool enabled)
        {
            respawnOnDeath = enabled;
        }

        public void Bind(Transform nextPlayer)
        {
            if (playerHealth != null)
            {
                playerHealth.Changed -= HandleHealthChanged;
            }
            player = nextPlayer;
            checkpoint = player == null ? Vector3.zero : player.position;
            playerHealth = player == null ? null : player.GetComponent<HealthComponent>();
            if (playerHealth != null)
            {
                playerHealth.Changed += HandleHealthChanged;
            }
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
            GameAudioCues.Raise(GameAudioCues.Checkpoint);
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
            if (playerHealth != null && !playerHealth.IsAlive)
            {
                playerHealth.SetMaximum(playerHealth.Maximum);
            }
        }

        private void HandleHealthChanged(float current, float maximum)
        {
            if (respawnOnDeath && current <= 0f)
            {
                Respawn();
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

using TeamIdle.GameTemplate.Common;
using UnityEngine;

namespace TeamIdle.GameTemplate.Prototype
{
    public sealed class PrototypeCameraFollow : MonoBehaviour
    {
        [SerializeField]
        private Transform target;

        [SerializeField]
        private Vector2 minimum = new(-7f, -1f);

        [SerializeField]
        private Vector2 maximum = new(12f, 3f);

        [SerializeField]
        private float smoothing = 6f;

        public void Bind(Transform nextTarget)
        {
            target = nextTarget;
        }

        private void LateUpdate()
        {
            if (target == null)
            {
                return;
            }

            var desired = new Vector3(
                Mathf.Clamp(target.position.x, minimum.x, maximum.x),
                Mathf.Clamp(target.position.y, minimum.y, maximum.y),
                transform.position.z
            );
            transform.position = Vector3.Lerp(
                transform.position,
                desired,
                1f - Mathf.Exp(-smoothing * Time.deltaTime)
            );
        }
    }

    public sealed class PrototypePlatformerStageController : MonoBehaviour
    {
        [SerializeField]
        private Transform player;

        [SerializeField]
        private float fallLimit = -7f;

        private Vector3 checkpoint;

        public int CheckpointIndex { get; private set; }

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

    public sealed class PrototypeCheckpoint : MonoBehaviour
    {
        [SerializeField]
        private int checkpointIndex;

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

    public sealed class PrototypeHazard : MonoBehaviour
    {
        [SerializeField]
        private float damage = 25f;

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

    public sealed class PrototypePatrolEnemy : MonoBehaviour
    {
        [SerializeField]
        private float range = 1.5f;

        [SerializeField]
        private float speed = 1.5f;

        private Vector3 origin;

        private void Awake()
        {
            origin = transform.position;
        }

        private void Update()
        {
            var offset = Mathf.PingPong(Time.time * speed, range * 2f) - range;
            transform.position = origin + Vector3.right * offset;
        }

        private void OnCollisionEnter2D(Collision2D collision)
        {
            if (collision.gameObject.CompareTag("Player"))
            {
                collision.gameObject.GetComponent<HealthComponent>()?.Damage(15f);
            }
        }
    }
}

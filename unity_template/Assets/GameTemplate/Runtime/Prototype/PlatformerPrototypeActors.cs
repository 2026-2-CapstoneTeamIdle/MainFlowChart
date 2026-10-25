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

        private float shakeEndsAt;
        private float shakeAmplitude;

        public Transform Target => target;

        public Vector2 Minimum => minimum;

        public Vector2 Maximum => maximum;

        public void Bind(Transform nextTarget)
        {
            target = nextTarget;
        }

        public void ConfigureBounds(float minimumX, float maximumX, float minimumY, float maximumY)
        {
            minimum = new Vector2(Mathf.Min(minimumX, maximumX), Mathf.Min(minimumY, maximumY));
            maximum = new Vector2(Mathf.Max(minimumX, maximumX), Mathf.Max(minimumY, maximumY));
        }

        public void Shake(float amplitude, float duration)
        {
            shakeAmplitude = Mathf.Max(shakeAmplitude, Mathf.Max(0f, amplitude));
            shakeEndsAt = Mathf.Max(shakeEndsAt, Time.unscaledTime + Mathf.Max(0f, duration));
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
            if (Time.unscaledTime < shakeEndsAt)
            {
                desired += (Vector3)(UnityEngine.Random.insideUnitCircle * shakeAmplitude);
            }
            else
            {
                shakeAmplitude = 0f;
            }
            transform.position = Vector3.Lerp(
                transform.position,
                desired,
                1f - Mathf.Exp(-smoothing * Time.deltaTime)
            );
        }
    }

    public sealed class PrototypePatrolEnemy : MonoBehaviour
    {
        [SerializeField]
        private string archetype = string.Empty;

        [SerializeField]
        private float range = 1.5f;

        [SerializeField]
        private float speed = 1.5f;

        [SerializeField]
        private float contactDamage = 15f;

        private Vector3 origin;

        public float Range => range;

        public float Speed => speed;

        public float ContactDamage => contactDamage;

        public string Archetype => archetype;

        public void Configure(
            string nextArchetype,
            float nextRange,
            float nextSpeed,
            float nextContactDamage
        )
        {
            archetype = nextArchetype ?? string.Empty;
            range = Mathf.Max(0.1f, nextRange);
            speed = Mathf.Max(0f, nextSpeed);
            contactDamage = Mathf.Max(0f, nextContactDamage);
        }

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
                collision.gameObject.GetComponent<HealthComponent>()?.Damage(contactDamage);
            }
        }
    }
}

using UnityEngine;

namespace TeamIdle.GameTemplate.Common
{
    public sealed class Projectile2D : MonoBehaviour
    {
        private Vector2 direction = Vector2.right;
        private float damage = 1f;
        private float speed = 8f;

        [SerializeField]
        private LayerMask targetMask = 1 << 8;

        private Rigidbody2D body;

        private void Awake()
        {
            body = GetComponent<Rigidbody2D>();
        }

        public void Launch(Vector2 nextDirection, float nextDamage, float nextSpeed, float lifetime)
        {
            direction = nextDirection.sqrMagnitude > 0f ? nextDirection.normalized : Vector2.right;
            damage = Mathf.Max(0f, nextDamage);
            speed = Mathf.Max(0f, nextSpeed);
            if (body != null && body.bodyType == RigidbodyType2D.Dynamic)
            {
                body.linearVelocity = direction * speed;
            }
            Destroy(gameObject, Mathf.Max(0.05f, lifetime));
        }

        private void Update()
        {
            if (body == null || body.bodyType != RigidbodyType2D.Dynamic)
            {
                transform.position += (Vector3)(direction * (speed * Time.deltaTime));
            }
        }

        private void OnTriggerEnter2D(Collider2D other)
        {
            if ((targetMask.value & (1 << other.gameObject.layer)) == 0)
            {
                return;
            }

            if (other.TryGetComponent<HealthComponent>(out var health))
            {
                health.Damage(damage);
                Destroy(gameObject);
            }
        }
    }
}

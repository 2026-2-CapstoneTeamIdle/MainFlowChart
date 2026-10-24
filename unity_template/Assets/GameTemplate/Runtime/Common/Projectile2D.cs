using UnityEngine;

namespace TeamIdle.GameTemplate.Common
{
    public sealed class Projectile2D : MonoBehaviour
    {
        private Vector2 direction = Vector2.right;
        private float damage = 1f;
        private float speed = 8f;

        public void Launch(Vector2 nextDirection, float nextDamage, float nextSpeed, float lifetime)
        {
            direction = nextDirection.sqrMagnitude > 0f ? nextDirection.normalized : Vector2.right;
            damage = Mathf.Max(0f, nextDamage);
            speed = Mathf.Max(0f, nextSpeed);
            Destroy(gameObject, Mathf.Max(0.05f, lifetime));
        }

        private void Update()
        {
            transform.position += (Vector3)(direction * (speed * Time.deltaTime));
        }

        private void OnTriggerEnter2D(Collider2D other)
        {
            if (other.TryGetComponent<HealthComponent>(out var health))
            {
                health.Damage(damage);
                Destroy(gameObject);
            }
        }
    }
}

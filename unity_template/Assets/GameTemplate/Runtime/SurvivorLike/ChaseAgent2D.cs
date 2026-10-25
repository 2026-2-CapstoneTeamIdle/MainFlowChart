using TeamIdle.GameTemplate.Common;
using UnityEngine;

namespace TeamIdle.GameTemplate.SurvivorLike
{
    public sealed class ChaseAgent2D : MonoBehaviour
    {
        [SerializeField]
        private Transform target;

        [SerializeField]
        private float speed = 2f;

        [SerializeField]
        private float contactDamage = 1f;

        [SerializeField]
        private float contactCooldown = 0.75f;

        private float nextContactTime;

        public Transform Target => target;

        public void SetTarget(Transform nextTarget)
        {
            target = nextTarget;
        }

        private void FixedUpdate()
        {
            if (target == null)
            {
                return;
            }

            var body = GetComponent<Rigidbody2D>();
            var next = Vector2.MoveTowards(
                transform.position,
                target.position,
                speed * Time.fixedDeltaTime
            );
            if (body != null)
            {
                body.MovePosition(next);
            }
            else
            {
                transform.position = next;
            }
        }

        private void OnCollisionStay2D(Collision2D collision)
        {
            if (Time.time < nextContactTime || !collision.gameObject.CompareTag("Player"))
            {
                return;
            }

            if (collision.gameObject.TryGetComponent<HealthComponent>(out var health))
            {
                health.Damage(contactDamage);
                nextContactTime = Time.time + Mathf.Max(0.05f, contactCooldown);
            }
        }
    }
}

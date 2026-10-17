using TeamIdle.GameTemplate.Common;
using TeamIdle.GameTemplate.Core;
using UnityEngine;

namespace TeamIdle.GameTemplate.Platformer
{
    [DefaultExecutionOrder(50)]
    public sealed class WallClimbModule : GameModuleBehaviour
    {
        [SerializeField]
        private Rigidbody2D target;

        [SerializeField]
        private float climbSpeed = 4f;

        [SerializeField]
        private float wallCheckDistance = 0.65f;

        [SerializeField]
        private float inputThreshold = 0.1f;

        private InputAdapterModule input;
        private float defaultGravityScale;
        private bool isClimbing;

        public override string ModuleId => "wall_climb";

        public bool IsClimbing => isClimbing;

        public void Bind(Rigidbody2D body)
        {
            RestoreGravity();
            target = body;
            if (target != null)
            {
                defaultGravityScale = target.gravityScale;
            }
        }

        protected override void OnInitialize(GameContext context)
        {
            input = context.GetRequired<InputAdapterModule>();
            if (target != null)
            {
                defaultGravityScale = target.gravityScale;
            }

            context.Register(this);
        }

        private void FixedUpdate()
        {
            if (!IsInitialized || target == null)
            {
                return;
            }

            var movement = input.Movement;
            var direction = movement.x > inputThreshold ? Vector2.right : Vector2.zero;
            if (movement.x < -inputThreshold)
            {
                direction = Vector2.left;
            }

            var shouldClimb =
                direction != Vector2.zero
                && Mathf.Abs(movement.y) > inputThreshold
                && HasWall(direction);
            if (!shouldClimb)
            {
                RestoreGravity();
                return;
            }

            isClimbing = true;
            target.gravityScale = 0f;
            target.linearVelocity = new Vector2(target.linearVelocity.x, movement.y * climbSpeed);
        }

        private bool HasWall(Vector2 direction)
        {
            foreach (var hit in Physics2D.RaycastAll(target.position, direction, wallCheckDistance))
            {
                if (hit.collider == null || hit.collider.isTrigger || hit.rigidbody == target)
                {
                    continue;
                }

                return true;
            }

            return false;
        }

        private void OnDisable()
        {
            RestoreGravity();
        }

        private void RestoreGravity()
        {
            if (target != null && isClimbing)
            {
                target.gravityScale = defaultGravityScale;
            }

            isClimbing = false;
        }
    }
}

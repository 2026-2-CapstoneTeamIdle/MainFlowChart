using TeamIdle.GameTemplate.Common;
using TeamIdle.GameTemplate.Core;
using UnityEngine;

namespace TeamIdle.GameTemplate.Platformer
{
    public sealed class PlatformerMovementModule : GameModuleBehaviour
    {
        [SerializeField]
        private Rigidbody2D target;

        [SerializeField]
        private Transform groundCheck;

        [SerializeField]
        private LayerMask groundMask = -1;

        [SerializeField]
        private float moveSpeed = 6f;

        [SerializeField]
        private float jumpVelocity = 12f;

        [SerializeField]
        private float groundRadius = 0.15f;

        [SerializeField]
        private float jumpBufferSeconds = 0.15f;

        [SerializeField]
        private float coyoteTimeSeconds = 0.2f;

        [SerializeField]
        private float blockedSpeedThreshold = 0.1f;

        [SerializeField]
        private float forwardObstacleDistance = 0.55f;

        private InputAdapterModule input;
        private float jumpQueuedUntil = float.NegativeInfinity;
        private float groundedUntil = float.NegativeInfinity;
        private bool blockedJumpAvailable;

        public override string ModuleId => "platformer_movement";

        public float MoveSpeed => moveSpeed;

        public float JumpVelocity => jumpVelocity;

        public void Configure(float nextMoveSpeed, float nextJumpVelocity)
        {
            moveSpeed = Mathf.Max(0.1f, nextMoveSpeed);
            jumpVelocity = Mathf.Max(0.1f, nextJumpVelocity);
        }

        public void Bind(Rigidbody2D body, Transform nextGroundCheck = null)
        {
            target = body;
            groundCheck = nextGroundCheck;
        }

        protected override void OnInitialize(GameContext context)
        {
            input = context.GetRequired<InputAdapterModule>();
            context.Register(this);
        }

        private void Update()
        {
            if (IsInitialized && input.ConfirmPressed)
            {
                jumpQueuedUntil = Time.time + jumpBufferSeconds;
            }
        }

        private void FixedUpdate()
        {
            if (!IsInitialized || target == null)
            {
                return;
            }

            var movementX = input.Movement.x;
            var velocity = target.linearVelocity;
            var wasBlocked =
                Mathf.Abs(movementX) > 0.1f && Mathf.Abs(velocity.x) <= blockedSpeedThreshold;
            velocity.x = movementX * moveSpeed;
            target.linearVelocity = velocity;

            if (IsGrounded())
            {
                groundedUntil = Time.time + coyoteTimeSeconds;
                blockedJumpAvailable = true;
            }

            var bufferedJump = Time.time <= jumpQueuedUntil;
            var canUseGroundJump = Time.time <= groundedUntil;
            var canUseBlockedJump =
                blockedJumpAvailable && wasBlocked && HasForwardObstacle(movementX);
            if (bufferedJump && (canUseGroundJump || canUseBlockedJump))
            {
                target.linearVelocity = new Vector2(target.linearVelocity.x, jumpVelocity);
                jumpQueuedUntil = float.NegativeInfinity;
                groundedUntil = float.NegativeInfinity;
                blockedJumpAvailable = false;
            }
        }

        private bool HasForwardObstacle(float movementX)
        {
            if (Mathf.Abs(movementX) <= 0.1f)
            {
                return false;
            }

            var direction = movementX > 0f ? Vector2.right : Vector2.left;
            foreach (
                var hit in Physics2D.RaycastAll(target.position, direction, forwardObstacleDistance)
            )
            {
                if (hit.collider == null || hit.collider.isTrigger || hit.rigidbody == target)
                {
                    continue;
                }

                return true;
            }

            return false;
        }

        private bool IsGrounded()
        {
            var position = groundCheck == null ? target.position : (Vector2)groundCheck.position;
            foreach (var overlap in Physics2D.OverlapCircleAll(position, groundRadius, groundMask))
            {
                if (overlap == null || overlap.isTrigger || overlap.attachedRigidbody == target)
                {
                    continue;
                }

                return true;
            }

            return false;
        }
    }
}

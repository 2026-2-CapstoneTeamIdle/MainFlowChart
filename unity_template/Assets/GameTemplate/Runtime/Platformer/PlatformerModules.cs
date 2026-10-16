using System;
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

        private InputAdapterModule input;
        private float jumpQueuedUntil = float.NegativeInfinity;

        public override string ModuleId => "platformer_movement";

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

            var velocity = target.linearVelocity;
            velocity.x = input.Movement.x * moveSpeed;
            target.linearVelocity = velocity;

            if (Time.time <= jumpQueuedUntil && IsGrounded())
            {
                target.linearVelocity = new Vector2(target.linearVelocity.x, jumpVelocity);
                jumpQueuedUntil = float.NegativeInfinity;
            }
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

    [DefaultExecutionOrder(100)]
    public sealed class AirDashModule : GameModuleBehaviour
    {
        [SerializeField]
        private Rigidbody2D target;

        [SerializeField]
        private Transform groundCheck;

        [SerializeField]
        private LayerMask groundMask = -1;

        [SerializeField]
        private float dashSpeed = 13f;

        [SerializeField]
        private float dashDuration = 0.16f;

        [SerializeField]
        private float groundRadius = 0.15f;

        private InputAdapterModule input;
        private float defaultGravityScale;
        private float dashEndsAt;
        private float facingDirection = 1f;
        private bool dashAvailable = true;
        private bool dashQueued;
        private bool isDashing;
        private Vector2 dashDirection;

        public override string ModuleId => "air_dash";

        public bool IsDashing => isDashing;

        public bool DashAvailable => dashAvailable;

        public void Bind(Rigidbody2D body, Transform nextGroundCheck = null)
        {
            FinishDash();
            target = body;
            groundCheck = nextGroundCheck;
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

        private void Update()
        {
            if (!IsInitialized || target == null)
            {
                return;
            }

            if (Mathf.Abs(input.Movement.x) > 0.1f)
            {
                facingDirection = Mathf.Sign(input.Movement.x);
            }

            if (input.DashPressed && !isDashing)
            {
                dashQueued = true;
            }
        }

        private void FixedUpdate()
        {
            if (!IsInitialized || target == null)
            {
                return;
            }

            var grounded = IsGrounded();
            if (grounded && !isDashing)
            {
                dashAvailable = true;
            }

            if (dashQueued)
            {
                dashQueued = false;
                if (!grounded && dashAvailable)
                {
                    StartDash();
                }
            }

            if (!isDashing)
            {
                return;
            }

            if (Time.time >= dashEndsAt)
            {
                FinishDash();
                return;
            }

            target.linearVelocity = dashDirection * dashSpeed;
        }

        private void StartDash()
        {
            dashDirection = input.Movement.normalized;
            if (dashDirection.sqrMagnitude < 0.01f)
            {
                dashDirection = new Vector2(facingDirection, 0f);
            }

            defaultGravityScale = target.gravityScale;
            target.gravityScale = 0f;
            target.linearVelocity = dashDirection * dashSpeed;
            dashEndsAt = Time.time + dashDuration;
            dashAvailable = false;
            isDashing = true;
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

        private void OnDisable()
        {
            FinishDash();
        }

        private void FinishDash()
        {
            if (target != null && isDashing)
            {
                target.gravityScale = defaultGravityScale;
            }

            isDashing = false;
            dashQueued = false;
        }
    }

    public sealed class CollectibleSystemModule : GameModuleBehaviour
    {
        [SerializeField]
        private int requiredCount;

        public override string ModuleId => "collectible_system";

        public int CollectedCount { get; private set; }

        public bool RequirementMet => CollectedCount >= requiredCount;

        public event Action<int, int> Collected;

        public void Collect(int amount = 1)
        {
            CollectedCount = Mathf.Max(0, CollectedCount + amount);
            Collected?.Invoke(CollectedCount, requiredCount);
        }

        protected override void OnInitialize(GameContext context)
        {
            context.Register(this);
        }
    }

    public sealed class GoalSystemModule : GameModuleBehaviour
    {
        private CollectibleSystemModule collectibles;

        public override string ModuleId => "goal_system";

        public bool IsCompleted { get; private set; }

        public event Action Completed;

        public bool TryComplete()
        {
            if (IsCompleted || (collectibles != null && !collectibles.RequirementMet))
            {
                return false;
            }

            IsCompleted = true;
            Completed?.Invoke();
            return true;
        }

        protected override void OnInitialize(GameContext context)
        {
            context.TryGet(out collectibles);
            context.Register(this);
        }
    }
}

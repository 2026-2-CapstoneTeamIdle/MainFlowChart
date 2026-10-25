using TeamIdle.GameTemplate.Common;
using TeamIdle.GameTemplate.Core;
using UnityEngine;

namespace TeamIdle.GameTemplate.Platformer
{
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
}

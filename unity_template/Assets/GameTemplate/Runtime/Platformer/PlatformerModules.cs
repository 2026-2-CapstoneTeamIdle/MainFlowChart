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

using TeamIdle.GameTemplate.Common;
using TeamIdle.GameTemplate.Core;
using UnityEngine;

namespace TeamIdle.GameTemplate.SurvivorLike
{
    public sealed class TopDownMovementModule : GameModuleBehaviour
    {
        [SerializeField]
        private Rigidbody2D target;

        [SerializeField]
        private float moveSpeed = 5f;
        private InputAdapterModule input;
        public override string ModuleId => "top_down_movement";
        public float MoveSpeed
        {
            get => moveSpeed;
            set => moveSpeed = Mathf.Max(0f, value);
        }

        public void Bind(Rigidbody2D body) => target = body;

        protected override void OnInitialize(GameContext context)
        {
            input = context.GetRequired<InputAdapterModule>();
            context.Register(this);
        }

        private void FixedUpdate()
        {
            if (IsInitialized && target != null)
                target.linearVelocity = input.Movement.normalized * moveSpeed;
        }
    }
}

using System;
using TeamIdle.GameTemplate.Core;

namespace TeamIdle.GameTemplate.Platformer
{
    public sealed class GoalSystemModule : GameModuleBehaviour
    {
        private CollectibleSystemModule collectibles;

        public override string ModuleId => "goal_system";

        public CollectibleSystemModule Collectibles => collectibles;

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

using System;
using TeamIdle.GameTemplate.Core;
using UnityEngine;

namespace TeamIdle.GameTemplate.Platformer
{
    public sealed class CollectibleSystemModule : GameModuleBehaviour
    {
        [SerializeField]
        private int requiredCount;

        public override string ModuleId => "collectible_system";

        public int CollectedCount { get; private set; }

        public int RequiredCount => requiredCount;

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
}

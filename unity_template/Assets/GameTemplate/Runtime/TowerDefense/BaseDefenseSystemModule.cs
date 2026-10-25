using System;
using TeamIdle.GameTemplate.Core;
using UnityEngine;

namespace TeamIdle.GameTemplate.TowerDefense
{
    public sealed class BaseDefenseSystemModule : GameModuleBehaviour
    {
        [SerializeField]
        private int startingLives = 20;
        public override string ModuleId => "base_defense_system";
        public int Lives { get; private set; }
        public event Action<int> LivesChanged;
        public event Action Defeated;

        public void LoseLives(int amount = 1)
        {
            Lives = Mathf.Max(0, Lives - Mathf.Max(0, amount));
            LivesChanged?.Invoke(Lives);
            if (Lives == 0)
                Defeated?.Invoke();
        }

        protected override void OnInitialize(GameContext context)
        {
            Lives = Mathf.Max(1, startingLives);
            context.Register(this);
        }
    }
}

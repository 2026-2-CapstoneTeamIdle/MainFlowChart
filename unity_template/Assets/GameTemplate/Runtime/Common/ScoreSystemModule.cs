using System;
using TeamIdle.GameTemplate.Core;
using UnityEngine;

namespace TeamIdle.GameTemplate.Common
{
    public sealed class ScoreSystemModule : GameModuleBehaviour
    {
        private GameStateStoreModule stateStore;
        private SaveSystemModule saveSystem;
        public override string ModuleId => "score_system";
        public int Score { get; private set; }
        public event Action<int> Changed;

        public void Add(int amount)
        {
            if (amount <= 0)
                return;
            Score += amount;
            stateStore?.SetInt("score", Score);
            Changed?.Invoke(Score);
        }

        public void ResetScore()
        {
            Score = 0;
            stateStore?.SetInt("score", Score);
            Changed?.Invoke(Score);
        }

        protected override void OnInitialize(GameContext context)
        {
            context.TryGet(out stateStore);
            context.TryGet(out saveSystem);
            ReloadFromStateStore();
            if (saveSystem != null)
                saveSystem.Loaded += ReloadFromStateStore;
            context.Register(this);
        }

        protected override void OnShutdown()
        {
            if (saveSystem != null)
                saveSystem.Loaded -= ReloadFromStateStore;
        }

        private void ReloadFromStateStore()
        {
            Score = Mathf.Max(0, stateStore?.GetInt("score") ?? 0);
            Changed?.Invoke(Score);
        }
    }
}

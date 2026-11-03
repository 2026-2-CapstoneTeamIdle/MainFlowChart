using System;
using TeamIdle.GameTemplate.Core;
using UnityEngine;

namespace TeamIdle.GameTemplate.Common
{
    public sealed class GameTimerModule : GameModuleBehaviour
    {
        [SerializeField]
        private float durationSeconds;

        [SerializeField]
        private bool startAutomatically = true;

        public override string ModuleId => "game_timer";
        public float ElapsedSeconds { get; private set; }
        public float RemainingSeconds =>
            durationSeconds > 0f ? Mathf.Max(0f, durationSeconds - ElapsedSeconds) : 0f;
        public bool IsRunning { get; private set; }
        public bool IsComplete => durationSeconds > 0f && ElapsedSeconds >= durationSeconds;
        public event Action<float, float> Changed;
        public event Action Completed;

        private void Update()
        {
            Tick(Time.deltaTime);
        }

        public void Configure(float duration, bool start = true)
        {
            durationSeconds = Mathf.Max(0f, duration);
            ElapsedSeconds = 0f;
            IsRunning = start;
        }

        public void StartTimer() => IsRunning = true;

        public void PauseTimer() => IsRunning = false;

        public void Tick(float deltaSeconds)
        {
            if (!IsRunning || deltaSeconds <= 0f || IsComplete)
                return;
            ElapsedSeconds += deltaSeconds;
            if (durationSeconds > 0f)
                ElapsedSeconds = Mathf.Min(ElapsedSeconds, durationSeconds);
            Changed?.Invoke(ElapsedSeconds, RemainingSeconds);
            if (IsComplete)
            {
                IsRunning = false;
                Completed?.Invoke();
            }
        }

        protected override void OnInitialize(GameContext context)
        {
            ElapsedSeconds = 0f;
            IsRunning = startAutomatically;
            context.Register(this);
        }
    }
}

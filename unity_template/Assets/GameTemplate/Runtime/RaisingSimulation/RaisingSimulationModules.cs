using System;
using System.Collections.Generic;
using TeamIdle.GameTemplate.Core;
using UnityEngine;

namespace TeamIdle.GameTemplate.RaisingSimulation
{
    [Serializable]
    public sealed class StatValue
    {
        public string statId = string.Empty;
        public int value;
        public int minimum;
        public int maximum = 100;
    }

    public sealed class StatSystemModule : GameModuleBehaviour
    {
        [SerializeField]
        private List<StatValue> initialStats = new();

        private readonly Dictionary<string, StatValue> stats = new(StringComparer.Ordinal);

        public override string ModuleId => "stat_system";

        public event Action<string, int> Changed;

        public int Get(string statId, int fallback = 0)
        {
            return stats.TryGetValue(statId, out var stat) ? stat.value : fallback;
        }

        public int Modify(string statId, int amount)
        {
            if (!stats.TryGetValue(statId, out var stat))
            {
                stat = new StatValue
                {
                    statId = statId,
                    minimum = 0,
                    maximum = 100,
                };
                stats[statId] = stat;
            }

            stat.value = Mathf.Clamp(stat.value + amount, stat.minimum, stat.maximum);
            Changed?.Invoke(statId, stat.value);
            return stat.value;
        }

        protected override void OnInitialize(GameContext context)
        {
            stats.Clear();
            foreach (var stat in initialStats)
            {
                if (!string.IsNullOrWhiteSpace(stat.statId))
                {
                    stat.value = Mathf.Clamp(stat.value, stat.minimum, stat.maximum);
                    stats[stat.statId] = stat;
                }
            }

            context.Register(this);
        }
    }

    public sealed class TimeTurnSystemModule : GameModuleBehaviour
    {
        [SerializeField]
        private int turnsPerDay = 3;

        [SerializeField]
        private int totalDays = 30;

        public override string ModuleId => "time_turn_system";

        public int Day { get; private set; }

        public int TurnInDay { get; private set; }

        public bool IsComplete => Day > totalDays;

        public event Action<int, int> Advanced;

        public event Action PeriodCompleted;

        public void Advance(int turns = 1)
        {
            for (var index = 0; index < Mathf.Max(1, turns); index++)
            {
                TurnInDay++;
                if (TurnInDay >= turnsPerDay)
                {
                    TurnInDay = 0;
                    Day++;
                }

                Advanced?.Invoke(Day, TurnInDay);
                if (IsComplete)
                {
                    PeriodCompleted?.Invoke();
                    break;
                }
            }
        }

        protected override void OnInitialize(GameContext context)
        {
            Day = 1;
            TurnInDay = 0;
            context.Register(this);
        }
    }

    [Serializable]
    public sealed class ActivityDefinition
    {
        [Serializable]
        public sealed class StatChange
        {
            public string statId = string.Empty;
            public int amount;
        }

        public string activityId = string.Empty;
        public int turnCost = 1;
        public List<StatChange> changes = new();
    }

    public sealed class ActivitySystemModule : GameModuleBehaviour
    {
        private StatSystemModule stats;
        private TimeTurnSystemModule time;

        public override string ModuleId => "activity_system";

        public event Action<ActivityDefinition> ActivityCompleted;

        public bool Execute(ActivityDefinition activity)
        {
            if (activity == null || time.IsComplete)
            {
                return false;
            }

            foreach (var change in activity.changes)
            {
                stats.Modify(change.statId, change.amount);
            }

            time.Advance(activity.turnCost);
            ActivityCompleted?.Invoke(activity);
            return true;
        }

        protected override void OnInitialize(GameContext context)
        {
            stats = context.GetRequired<StatSystemModule>();
            time = context.GetRequired<TimeTurnSystemModule>();
            context.Register(this);
        }
    }

    public sealed class ScheduleSystemModule : GameModuleBehaviour
    {
        [Serializable]
        private sealed class ScheduledEvent
        {
            public string eventId = string.Empty;
            public int day = 1;
            public int turn;
        }

        [SerializeField]
        private List<ScheduledEvent> events = new();

        private TimeTurnSystemModule time;

        public override string ModuleId => "schedule_system";

        public event Action<string> Triggered;

        protected override void OnInitialize(GameContext context)
        {
            time = context.GetRequired<TimeTurnSystemModule>();
            time.Advanced += OnAdvanced;
            context.Register(this);
        }

        protected override void OnShutdown()
        {
            if (time != null)
            {
                time.Advanced -= OnAdvanced;
            }
        }

        private void OnAdvanced(int day, int turn)
        {
            foreach (var scheduledEvent in events)
            {
                if (scheduledEvent.day == day && scheduledEvent.turn == turn)
                {
                    Triggered?.Invoke(scheduledEvent.eventId);
                }
            }
        }
    }

    public sealed class RaisingEndingResolverModule : GameModuleBehaviour
    {
        [Serializable]
        private sealed class EndingRule
        {
            public string endingId = string.Empty;
            public string statId = string.Empty;
            public int minimumValue;
            public int priority;
        }

        [SerializeField]
        private List<EndingRule> endings = new();

        private StatSystemModule stats;

        public override string ModuleId => "raising_ending_resolver";

        public string Resolve(string fallbackEndingId = "default")
        {
            EndingRule selected = null;
            foreach (var ending in endings)
            {
                if (stats.Get(ending.statId) < ending.minimumValue)
                {
                    continue;
                }

                if (selected == null || ending.priority > selected.priority)
                {
                    selected = ending;
                }
            }

            return selected?.endingId ?? fallbackEndingId;
        }

        protected override void OnInitialize(GameContext context)
        {
            stats = context.GetRequired<StatSystemModule>();
            context.Register(this);
        }
    }
}

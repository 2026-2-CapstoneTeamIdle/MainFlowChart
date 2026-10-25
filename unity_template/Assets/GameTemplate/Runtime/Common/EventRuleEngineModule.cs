using System;
using System.Collections.Generic;
using TeamIdle.GameTemplate.Core;

namespace TeamIdle.GameTemplate.Common
{
    public sealed class EventRuleEngineModule : GameModuleBehaviour
    {
        private sealed class Rule
        {
            public string EventId;
            public Func<bool> Condition;
            public Action Action;
            public bool Once;
        }

        private readonly List<Rule> rules = new();
        public override string ModuleId => "event_rule_engine";
        public event Action<string> EventPublished;

        public void AddRule(string eventId, Func<bool> condition, Action action, bool once = false)
        {
            if (string.IsNullOrWhiteSpace(eventId))
                throw new ArgumentException("Event ID cannot be empty.", nameof(eventId));
            rules.Add(
                new Rule
                {
                    EventId = eventId,
                    Condition = condition ?? (() => true),
                    Action = action ?? throw new ArgumentNullException(nameof(action)),
                    Once = once,
                }
            );
        }

        public int Publish(string eventId)
        {
            EventPublished?.Invoke(eventId);
            var executed = 0;
            for (var index = rules.Count - 1; index >= 0; index--)
            {
                var rule = rules[index];
                if (rule.EventId != eventId || !rule.Condition())
                    continue;
                rule.Action();
                executed++;
                if (rule.Once)
                    rules.RemoveAt(index);
            }
            return executed;
        }

        protected override void OnInitialize(GameContext context) => context.Register(this);

        protected override void OnShutdown() => rules.Clear();
    }
}

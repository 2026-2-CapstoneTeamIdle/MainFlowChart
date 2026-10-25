#if false // Compatibility shell: MonoBehaviours were moved to filename-matched scripts.
using System;
using System.Collections.Generic;
using System.Globalization;
using TeamIdle.GameTemplate.Core;
using UnityEngine;

namespace TeamIdle.GameTemplate.Common
{
    public sealed class GameStateStoreModule : GameModuleBehaviour
    {
        [Serializable]
        public sealed class Entry
        {
            public string key = string.Empty;
            public string value = string.Empty;
        }

        [SerializeField]
        private List<Entry> initialValues = new();

        private readonly Dictionary<string, string> values = new(StringComparer.Ordinal);

        public override string ModuleId => "game_state_store";

        public event Action<string, string> ValueChanged;

        public void SetString(string key, string value)
        {
            RequireKey(key);
            values[key] = value ?? string.Empty;
            ValueChanged?.Invoke(key, values[key]);
        }

        public string GetString(string key, string fallback = "")
        {
            return values.TryGetValue(key, out var value) ? value : fallback;
        }

        public void SetInt(string key, int value)
        {
            SetString(key, value.ToString(CultureInfo.InvariantCulture));
        }

        public int GetInt(string key, int fallback = 0)
        {
            return int.TryParse(
                GetString(key),
                NumberStyles.Integer,
                CultureInfo.InvariantCulture,
                out var value
            )
                ? value
                : fallback;
        }

        public void SetFloat(string key, float value)
        {
            SetString(key, value.ToString(CultureInfo.InvariantCulture));
        }

        public float GetFloat(string key, float fallback = 0f)
        {
            return float.TryParse(
                GetString(key),
                NumberStyles.Float,
                CultureInfo.InvariantCulture,
                out var value
            )
                ? value
                : fallback;
        }

        public IReadOnlyList<Entry> CreateSnapshot()
        {
            var snapshot = new List<Entry>(values.Count);
            foreach (var pair in values)
            {
                snapshot.Add(new Entry { key = pair.Key, value = pair.Value });
            }

            return snapshot;
        }

        public void Restore(IEnumerable<Entry> snapshot)
        {
            values.Clear();
            foreach (var entry in snapshot)
            {
                if (!string.IsNullOrWhiteSpace(entry.key))
                {
                    values[entry.key] = entry.value ?? string.Empty;
                }
            }
        }

        protected override void OnInitialize(GameContext context)
        {
            Restore(initialValues);
            context.Register(this);
        }

        private static void RequireKey(string key)
        {
            if (string.IsNullOrWhiteSpace(key))
            {
                throw new ArgumentException("State key cannot be empty.", nameof(key));
            }
        }
    }

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
            {
                throw new ArgumentException("Event ID cannot be empty.", nameof(eventId));
            }

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
                {
                    continue;
                }

                rule.Action();
                executed++;
                if (rule.Once)
                {
                    rules.RemoveAt(index);
                }
            }

            return executed;
        }

        protected override void OnInitialize(GameContext context)
        {
            context.Register(this);
        }

        protected override void OnShutdown()
        {
            rules.Clear();
        }
    }

    public sealed class SaveSystemModule : GameModuleBehaviour
    {
        [Serializable]
        private sealed class SaveData
        {
            public List<GameStateStoreModule.Entry> entries = new();
        }

        [SerializeField]
        private string playerPrefsKey = "team_idle_game_save";

        private GameStateStoreModule stateStore;

        public override string ModuleId => "save_system";

        public void Save()
        {
            var data = new SaveData
            {
                entries = new List<GameStateStoreModule.Entry>(stateStore.CreateSnapshot()),
            };
            PlayerPrefs.SetString(playerPrefsKey, JsonUtility.ToJson(data));
            PlayerPrefs.Save();
        }

        public bool Load()
        {
            if (!PlayerPrefs.HasKey(playerPrefsKey))
            {
                return false;
            }

            var data = JsonUtility.FromJson<SaveData>(PlayerPrefs.GetString(playerPrefsKey));
            stateStore.Restore(data?.entries ?? new List<GameStateStoreModule.Entry>());
            return true;
        }

        public void DeleteSave()
        {
            PlayerPrefs.DeleteKey(playerPrefsKey);
        }

        protected override void OnInitialize(GameContext context)
        {
            stateStore = context.GetRequired<GameStateStoreModule>();
            context.Register(this);
        }
    }
}
#endif

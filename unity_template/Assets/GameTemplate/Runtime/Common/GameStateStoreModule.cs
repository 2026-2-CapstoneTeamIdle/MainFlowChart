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
            if (string.IsNullOrWhiteSpace(key))
                throw new ArgumentException("State key cannot be empty.", nameof(key));
            values[key] = value ?? string.Empty;
            ValueChanged?.Invoke(key, values[key]);
        }

        public string GetString(string key, string fallback = "") =>
            values.TryGetValue(key, out var value) ? value : fallback;

        public void SetInt(string key, int value) =>
            SetString(key, value.ToString(CultureInfo.InvariantCulture));

        public int GetInt(string key, int fallback = 0) =>
            int.TryParse(
                GetString(key),
                NumberStyles.Integer,
                CultureInfo.InvariantCulture,
                out var value
            )
                ? value
                : fallback;

        public void SetFloat(string key, float value) =>
            SetString(key, value.ToString(CultureInfo.InvariantCulture));

        public float GetFloat(string key, float fallback = 0f) =>
            float.TryParse(
                GetString(key),
                NumberStyles.Float,
                CultureInfo.InvariantCulture,
                out var value
            )
                ? value
                : fallback;

        public IReadOnlyList<Entry> CreateSnapshot()
        {
            var snapshot = new List<Entry>(values.Count);
            foreach (var pair in values)
                snapshot.Add(new Entry { key = pair.Key, value = pair.Value });
            return snapshot;
        }

        public void Restore(IEnumerable<Entry> snapshot)
        {
            values.Clear();
            foreach (var entry in snapshot)
                if (!string.IsNullOrWhiteSpace(entry.key))
                    values[entry.key] = entry.value ?? string.Empty;
        }

        protected override void OnInitialize(GameContext context)
        {
            Restore(initialValues);
            context.Register(this);
        }
    }
}

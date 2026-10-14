using System;
using System.Collections.Generic;
using System.IO;
using UnityEngine;

namespace TeamIdle.GameTemplate.Editor
{
    [Serializable]
    public sealed class GameImplementationPlan
    {
        public const string AssetPath = "Assets/GameTemplate/Generated/GameImplementationPlan.json";

        [Serializable]
        public sealed class ContentEntry
        {
            public string archetype = string.Empty;
            public int count;
            public string purpose = string.Empty;
        }

        [Serializable]
        public sealed class Scenario
        {
            public string scenario_id = string.Empty;
            public string title = string.Empty;
            public List<string> steps = new();
            public List<string> assertions = new();
        }

        public string plan_version = string.Empty;
        public string complexity_tier = string.Empty;
        public int minimum_session_minutes;
        public List<ContentEntry> content = new();
        public List<string> ui_screens = new();
        public List<Scenario> playtest_scenarios = new();

        public static GameImplementationPlan Load()
        {
            if (!File.Exists(AssetPath))
            {
                throw new FileNotFoundException("Game implementation plan is missing.", AssetPath);
            }

            var plan = JsonUtility.FromJson<GameImplementationPlan>(File.ReadAllText(AssetPath));
            if (
                plan == null
                || plan.complexity_tier != "advanced_prototype"
                || plan.playtest_scenarios.Count < 3
            )
            {
                throw new InvalidDataException("Game implementation plan is incomplete.");
            }

            return plan;
        }

        public int Count(string archetype, int fallback)
        {
            foreach (var entry in content)
            {
                if (entry.archetype == archetype)
                {
                    return Mathf.Max(1, entry.count);
                }
            }

            return fallback;
        }
    }
}

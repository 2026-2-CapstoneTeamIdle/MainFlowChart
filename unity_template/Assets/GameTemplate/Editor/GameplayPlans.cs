using System;
using System.Collections.Generic;
using System.IO;
using UnityEngine;

namespace TeamIdle.GameTemplate.Editor
{
    [Serializable]
    public sealed class ContentStat
    {
        public string stat_id = string.Empty;
        public float value;
    }

    [Serializable]
    public sealed class ContentDefinition
    {
        public string content_id = string.Empty;
        public string role = string.Empty;
        public int count;
        public List<ContentStat> stats = new();
        public List<string> behaviors = new();

        public float Stat(string statId, float fallback)
        {
            foreach (var stat in stats)
            {
                if (stat.stat_id == statId)
                {
                    return stat.value;
                }
            }

            return fallback;
        }
    }

    [Serializable]
    public sealed class ContentPlan
    {
        public const string AssetPath = "Assets/GameTemplate/Generated/Design/content_plan.json";

        public string plan_version = string.Empty;
        public List<ContentDefinition> enemies = new();
        public List<ContentDefinition> obstacles = new();
        public List<ContentDefinition> rewards = new();
        public List<string> stages = new();
        public string final_goal = string.Empty;

        public static ContentPlan Load()
        {
            if (!File.Exists(AssetPath))
            {
                throw new FileNotFoundException("Content plan is missing.", AssetPath);
            }

            var plan = JsonUtility.FromJson<ContentPlan>(File.ReadAllText(AssetPath));
            if (plan == null || plan.plan_version != "2.0.0")
            {
                throw new InvalidOperationException("Content plan is invalid or unsupported.");
            }

            return plan;
        }

        public ContentDefinition Find(string contentId)
        {
            foreach (var collection in new[] { enemies, obstacles, rewards })
            {
                foreach (var definition in collection)
                {
                    if (definition.content_id == contentId)
                    {
                        return definition;
                    }
                }
            }

            throw new InvalidOperationException($"Content definition is missing: {contentId}");
        }
    }

    [Serializable]
    public sealed class BalanceStat
    {
        public string stat_id = string.Empty;
        public float initial;
        public float minimum;
        public float maximum;
        public string unit = string.Empty;
    }

    [Serializable]
    public sealed class BalancePlan
    {
        public const string AssetPath = "Assets/GameTemplate/Generated/Design/balance_plan.json";

        public string plan_version = string.Empty;
        public List<BalanceStat> stats = new();
        public List<string> formulas = new();
        public List<string> difficulty_curve = new();
        public List<string> reward_costs = new();

        public static BalancePlan Load()
        {
            if (!File.Exists(AssetPath))
            {
                throw new FileNotFoundException("Balance plan is missing.", AssetPath);
            }

            var plan = JsonUtility.FromJson<BalancePlan>(File.ReadAllText(AssetPath));
            if (plan == null || plan.plan_version != "2.0.0")
            {
                throw new InvalidOperationException("Balance plan is invalid or unsupported.");
            }

            return plan;
        }

        public float Initial(string statId, float fallback)
        {
            foreach (var stat in stats)
            {
                if (stat.stat_id == statId)
                {
                    return Mathf.Clamp(stat.initial, stat.minimum, stat.maximum);
                }
            }

            return fallback;
        }
    }

    [Serializable]
    public sealed class PresentationCue
    {
        public string cue_id = string.Empty;
        public string trigger = string.Empty;
        public string visual_feedback = string.Empty;
        public string audio_asset_id = string.Empty;
    }

    [Serializable]
    public sealed class PresentationPlan
    {
        public const string AssetPath =
            "Assets/GameTemplate/Generated/Design/presentation_plan.json";

        public string plan_version = string.Empty;
        public List<string> ui_screens = new();
        public List<string> state_transitions = new();
        public List<PresentationCue> feedback_cues = new();
        public List<string> camera_effects = new();
        public List<string> particle_requests = new();
        public List<string> animation_requests = new();
        public List<string> required_image_asset_ids = new();
        public List<string> required_sound_asset_ids = new();

        public static PresentationPlan Load()
        {
            if (!File.Exists(AssetPath))
            {
                throw new FileNotFoundException("Presentation plan is missing.", AssetPath);
            }

            var plan = JsonUtility.FromJson<PresentationPlan>(File.ReadAllText(AssetPath));
            if (plan == null || plan.plan_version != "2.0.0")
            {
                throw new InvalidOperationException("Presentation plan is invalid or unsupported.");
            }

            return plan;
        }

        public bool HasCue(string cueId)
        {
            return feedback_cues.Exists(cue => cue.cue_id == cueId);
        }
    }

    [Serializable]
    public sealed class ValidationScenario
    {
        public string scenario_id = string.Empty;
        public string title = string.Empty;
        public List<string> steps = new();
        public List<string> assertions = new();
    }

    [Serializable]
    public sealed class ValidationRule
    {
        public string rule_id = string.Empty;
        public string description = string.Empty;
        public bool required;
    }

    [Serializable]
    public sealed class ValidationPlan
    {
        public const string AssetPath = "Assets/GameTemplate/Generated/Design/validation_plan.json";

        public string plan_version = string.Empty;
        public List<ValidationScenario> scenarios = new();
        public List<ValidationRule> rules = new();
        public List<string> required_scene_objects = new();
        public List<string> required_feature_bindings = new();

        public static ValidationPlan Load()
        {
            if (!File.Exists(AssetPath))
            {
                throw new FileNotFoundException("Validation plan is missing.", AssetPath);
            }

            var plan = JsonUtility.FromJson<ValidationPlan>(File.ReadAllText(AssetPath));
            if (
                plan == null
                || plan.plan_version != "2.0.0"
                || plan.scenarios.Count < 3
                || plan.rules.Count == 0
            )
            {
                throw new InvalidOperationException("Validation plan is invalid or incomplete.");
            }

            return plan;
        }

        public bool HasScenario(string scenarioId)
        {
            return scenarios.Exists(scenario => scenario.scenario_id == scenarioId);
        }
    }
}

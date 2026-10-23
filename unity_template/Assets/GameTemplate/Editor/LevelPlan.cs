using System;
using System.Collections.Generic;
using System.IO;
using UnityEngine;

namespace TeamIdle.GameTemplate.Editor
{
    [Serializable]
    public sealed class LevelPlacement
    {
        public string placement_id = string.Empty;
        public string archetype = string.Empty;
        public float x;
        public float y;
    }

    [Serializable]
    public sealed class LevelPlatform
    {
        public string platform_id = string.Empty;
        public string role = string.Empty;
        public float x;
        public float y;
        public float width;
        public float height;
    }

    [Serializable]
    public sealed class LevelZone
    {
        public string zone_id = string.Empty;
        public string title = string.Empty;
        public string purpose = string.Empty;
        public string challenge = string.Empty;
        public string reward = string.Empty;
        public int difficulty;
        public List<string> required_mechanics = new();
        public float start_x;
        public float end_x;
        public LevelPlacement checkpoint;
        public List<LevelPlatform> platforms = new();
        public List<LevelPlacement> hazards = new();
        public List<LevelPlacement> enemies = new();
        public List<LevelPlacement> collectibles = new();
    }

    [Serializable]
    public sealed class LevelPlan
    {
        public const string AssetPath = "Assets/GameTemplate/Generated/Design/level_plan.json";

        public string plan_version = string.Empty;
        public string genre = string.Empty;
        public LevelPlacement player_spawn = new();
        public LevelPlacement goal = new();
        public List<LevelZone> zones = new();
        public float safe_start_seconds;
        public float camera_orthographic_size;
        public float max_horizontal_gap;
        public float max_step_up;
        public float minimum_landing_width;

        public static LevelPlan Load()
        {
            if (!File.Exists(AssetPath))
            {
                throw new FileNotFoundException("Level plan is missing.", AssetPath);
            }

            var plan = JsonUtility.FromJson<LevelPlan>(File.ReadAllText(AssetPath));
            if (plan == null || plan.plan_version != "2.0.0")
            {
                throw new InvalidOperationException("Level plan is invalid or unsupported.");
            }

            if (plan.genre == "Platformer" && plan.zones.Count < 3)
            {
                throw new InvalidOperationException(
                    "Platformer level plan requires tutorial, challenge, and mastery zones."
                );
            }

            // JsonUtility can materialize a JSON null reference as an empty serializable object.
            // Convert that sentinel back to null so a mastery zone without a checkpoint does not
            // create a phantom checkpoint at world origin.
            foreach (var zone in plan.zones)
            {
                if (
                    zone.checkpoint != null
                    && string.IsNullOrWhiteSpace(zone.checkpoint.placement_id)
                )
                {
                    zone.checkpoint = null;
                }
            }

            return plan;
        }
    }
}

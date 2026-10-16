using System;
using System.Collections.Generic;
using System.IO;
using UnityEngine;

namespace TeamIdle.GameTemplate.Editor
{
    [Serializable]
    public sealed class GameBlueprint
    {
        public const string AssetPath = "Assets/GameTemplate/Generated/GameBlueprint.json";

        [Serializable]
        public sealed class ContentDirective
        {
            public string archetype = string.Empty;
            public int count;
            public string purpose = string.Empty;
        }

        [Serializable]
        public sealed class EntityDirective
        {
            public string entity_id = string.Empty;
            public string display_name = string.Empty;
            public string archetype = string.Empty;
            public float position_x;
            public float position_y;
            public float scale_x = 1f;
            public float scale_y = 1f;
            public string color_hex = "#FFFFFF";
            public List<string> behavior_tags = new();
        }

        [Serializable]
        public sealed class ProgressionOption
        {
            public string option_id = string.Empty;
            public string display_name = string.Empty;
            public string description = string.Empty;
            public string rarity = "common";
        }

        public string blueprint_version = string.Empty;
        public string blueprint_id = string.Empty;
        public string source = string.Empty;
        public string title = string.Empty;
        public string summary = string.Empty;
        public float scene_width;
        public float scene_height;
        public string background_color_hex = "#1B2336";
        public List<string> core_loop = new();
        public List<ContentDirective> content = new();
        public List<EntityDirective> entities = new();
        public List<ProgressionOption> progression_options = new();
        public List<string> ui_labels = new();

        public static GameBlueprint Load()
        {
            if (!File.Exists(AssetPath))
            {
                throw new FileNotFoundException("Game blueprint is missing.", AssetPath);
            }

            var blueprint = JsonUtility.FromJson<GameBlueprint>(File.ReadAllText(AssetPath));
            if (
                blueprint == null
                || blueprint.blueprint_version != "1.0.0"
                || string.IsNullOrWhiteSpace(blueprint.blueprint_id)
                || blueprint.entities.Count < 2
                || blueprint.content.Count < 3
                || blueprint.core_loop.Count < 3
            )
            {
                throw new InvalidDataException("Game blueprint is incomplete.");
            }

            return blueprint;
        }

        public void ApplyContentTo(GameImplementationPlan plan)
        {
            foreach (var directive in content)
            {
                if (string.IsNullOrWhiteSpace(directive.archetype) || directive.count < 1)
                {
                    continue;
                }

                var existing = plan.content.Find(entry => entry.archetype == directive.archetype);
                if (existing == null)
                {
                    plan.content.Add(
                        new GameImplementationPlan.ContentEntry
                        {
                            archetype = directive.archetype,
                            count = directive.count,
                            purpose = directive.purpose,
                        }
                    );
                    continue;
                }

                existing.count = directive.count;
                existing.purpose = directive.purpose;
            }
        }

        public Color BackgroundColor(Color fallback)
        {
            return ColorUtility.TryParseHtmlString(background_color_hex, out var color)
                ? color
                : fallback;
        }
    }
}

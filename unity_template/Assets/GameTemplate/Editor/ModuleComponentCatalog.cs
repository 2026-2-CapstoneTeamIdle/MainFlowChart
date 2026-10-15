using System;
using System.Collections.Generic;
using System.Reflection;
using TeamIdle.GameTemplate.Card;
using TeamIdle.GameTemplate.Common;
using TeamIdle.GameTemplate.Core;
using TeamIdle.GameTemplate.Platformer;
using TeamIdle.GameTemplate.RaisingSimulation;
using TeamIdle.GameTemplate.SurvivorLike;
using TeamIdle.GameTemplate.TowerDefense;
using TeamIdle.GameTemplate.VisualNovel;
using UnityEngine;

namespace TeamIdle.GameTemplate.Editor
{
    public static class ModuleComponentCatalog
    {
        private static readonly IReadOnlyDictionary<string, Type> ModuleTypes = new Dictionary<
            string,
            Type
        >(StringComparer.Ordinal)
        {
            ["game_state_store"] = typeof(GameStateStoreModule),
            ["event_rule_engine"] = typeof(EventRuleEngineModule),
            ["scene_flow_manager"] = typeof(SceneFlowManagerModule),
            ["input_adapter"] = typeof(InputAdapterModule),
            ["save_system"] = typeof(SaveSystemModule),
            ["asset_registry"] = typeof(AssetRegistryModule),
            ["audio_manager"] = typeof(AudioManagerModule),
            ["ui_router"] = typeof(UiRouterModule),
            ["health_damage_system"] = typeof(HealthDamageSystemModule),
            ["projectile_system"] = typeof(ProjectileSystemModule),
            ["economy_system"] = typeof(EconomySystemModule),
            ["platformer_movement"] = typeof(PlatformerMovementModule),
            ["collectible_system"] = typeof(CollectibleSystemModule),
            ["goal_system"] = typeof(GoalSystemModule),
            ["wave_spawner"] = typeof(WaveSpawnerModule),
            ["tower_targeting_system"] = typeof(TowerTargetingSystemModule),
            ["base_defense_system"] = typeof(BaseDefenseSystemModule),
            ["deck_system"] = typeof(DeckSystemModule),
            ["turn_system"] = typeof(TurnSystemModule),
            ["card_resource_system"] = typeof(CardResourceSystemModule),
            ["card_effect_system"] = typeof(CardEffectSystemModule),
            ["dialogue_runner"] = typeof(DialogueRunnerModule),
            ["choice_branch_system"] = typeof(ChoiceBranchSystemModule),
            ["flag_system"] = typeof(FlagSystemModule),
            ["ending_resolver"] = typeof(EndingResolverModule),
            ["stat_system"] = typeof(StatSystemModule),
            ["time_turn_system"] = typeof(TimeTurnSystemModule),
            ["activity_system"] = typeof(ActivitySystemModule),
            ["schedule_system"] = typeof(ScheduleSystemModule),
            ["raising_ending_resolver"] = typeof(RaisingEndingResolverModule),
            ["top_down_movement"] = typeof(TopDownMovementModule),
            ["enemy_spawn_system"] = typeof(EnemySpawnSystemModule),
            ["auto_target_system"] = typeof(AutoTargetSystemModule),
            ["experience_system"] = typeof(ExperienceSystemModule),
            ["rarity_system"] = typeof(RaritySystemModule),
            ["upgrade_selection_system"] = typeof(UpgradeSelectionSystemModule),
        };

        private static Dictionary<string, Type> generatedModuleTypes;

        public static bool TryGetType(string moduleId, out Type moduleType)
        {
            if (ModuleTypes.TryGetValue(moduleId, out moduleType))
            {
                return true;
            }

            generatedModuleTypes ??= DiscoverGeneratedModuleTypes();
            return generatedModuleTypes.TryGetValue(moduleId, out moduleType);
        }

        private static Dictionary<string, Type> DiscoverGeneratedModuleTypes()
        {
            var discovered = new Dictionary<string, Type>(StringComparer.Ordinal);
            foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
            {
                Type[] types;
                try
                {
                    types = assembly.GetTypes();
                }
                catch (ReflectionTypeLoadException error)
                {
                    types = Array.FindAll(error.Types, type => type != null);
                }

                foreach (var type in types)
                {
                    if (
                        type == null
                        || type.IsAbstract
                        || !typeof(GameModuleBehaviour).IsAssignableFrom(type)
                    )
                    {
                        continue;
                    }

                    var attribute = type.GetCustomAttribute<GeneratedGameModuleAttribute>();
                    if (attribute == null || string.IsNullOrWhiteSpace(attribute.ModuleId))
                    {
                        continue;
                    }

                    if (ModuleTypes.ContainsKey(attribute.ModuleId))
                    {
                        throw new InvalidOperationException(
                            $"Generated module cannot replace template module: {attribute.ModuleId}"
                        );
                    }

                    if (!discovered.TryAdd(attribute.ModuleId, type))
                    {
                        throw new InvalidOperationException(
                            $"Duplicate generated module ID: {attribute.ModuleId}"
                        );
                    }
                }
            }

            return discovered;
        }

        public static void AddConfiguredModules(
            GameObject moduleRoot,
            IEnumerable<string> moduleIds,
            ValidationProbe validation
        )
        {
            var addedTypes = new HashSet<Type>();
            foreach (var moduleId in moduleIds)
            {
                if (!TryGetType(moduleId, out var moduleType))
                {
                    if (moduleId != "game_bootstrap" && moduleId != "validation_probe")
                    {
                        validation.Fail("template.unknown_module", moduleId);
                    }

                    continue;
                }

                if (addedTypes.Add(moduleType))
                {
                    moduleRoot.AddComponent(moduleType);
                }
            }
        }

        public static void ValidateForBatch()
        {
            var root = new GameObject("ModuleCatalogValidation");
            var validation = root.AddComponent<ValidationProbe>();
            var modules = new GameObject("Modules");
            modules.transform.SetParent(root.transform, false);

            AddConfiguredModules(modules, ModuleTypes.Keys, validation);

            var behaviours = modules.GetComponents<MonoBehaviour>();
            var moduleCount = 0;
            foreach (var behaviour in behaviours)
            {
                if (behaviour is IGameModule)
                {
                    moduleCount++;
                }
            }

            UnityEngine.Object.DestroyImmediate(root);
            if (moduleCount != ModuleTypes.Count)
            {
                throw new InvalidOperationException(
                    $"Expected {ModuleTypes.Count} attachable modules but found {moduleCount}."
                );
            }

            Debug.Log($"UNITY_MODULE_CATALOG_OK:{moduleCount}");
        }
    }
}

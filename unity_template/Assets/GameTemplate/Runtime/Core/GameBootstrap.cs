using System;
using System.Collections.Generic;
using UnityEngine;

namespace TeamIdle.GameTemplate.Core
{
    [DefaultExecutionOrder(-1000)]
    public sealed class GameBootstrap : MonoBehaviour
    {
        [SerializeField]
        private GameTemplateConfig config;

        [SerializeField]
        private Transform moduleRoot;

        [SerializeField]
        private ValidationProbe validationProbe;

        private readonly List<IGameModule> initializedModules = new();

        public static GameBootstrap Instance { get; private set; }

        public GameTemplateConfig Config => config;

        public IReadOnlyList<IGameModule> InitializedModules => initializedModules;

        public bool IsModuleInitialized(string moduleId)
        {
            return initializedModules.Exists(module => module.ModuleId == moduleId);
        }

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.SubsystemRegistration)]
        private static void ResetStatics()
        {
            Instance = null;
        }

        private void Awake()
        {
            if (Instance != null && Instance != this)
            {
                Destroy(gameObject);
                return;
            }

            Instance = this;
            DontDestroyOnLoad(gameObject);

            validationProbe ??= GetComponent<ValidationProbe>();
            if (validationProbe == null)
            {
                validationProbe = gameObject.AddComponent<ValidationProbe>();
            }

            if (config == null)
            {
                validationProbe.Fail("template.config", "GameTemplateConfig is missing.");
                enabled = false;
                return;
            }

            if (!config.IsValid(out var issue))
            {
                validationProbe.Fail("template.config", issue);
                enabled = false;
                return;
            }

            InitializeModules();
        }

        private void OnDestroy()
        {
            for (var index = initializedModules.Count - 1; index >= 0; index--)
            {
                initializedModules[index].Shutdown();
            }

            initializedModules.Clear();
            if (Instance == this)
            {
                Instance = null;
            }
        }

        private void InitializeModules()
        {
            var context = new GameContext(config, validationProbe);
            var root = moduleRoot == null ? transform : moduleRoot;
            var moduleIds = new HashSet<string>(StringComparer.Ordinal);
            var discovered = new Dictionary<string, IGameModule>(StringComparer.Ordinal);

            foreach (var behaviour in root.GetComponentsInChildren<MonoBehaviour>(true))
            {
                if (behaviour is not IGameModule module)
                {
                    continue;
                }

                if (string.IsNullOrWhiteSpace(module.ModuleId))
                {
                    validationProbe.Fail(
                        "template.module_id",
                        $"{behaviour.name} has an empty module ID."
                    );
                    continue;
                }

                if (!moduleIds.Add(module.ModuleId))
                {
                    validationProbe.Fail("template.duplicate_module", module.ModuleId);
                    continue;
                }

                discovered[module.ModuleId] = module;
            }

            foreach (var moduleId in config.SelectedModules)
            {
                if (moduleId == "game_bootstrap" || moduleId == "validation_probe")
                {
                    continue;
                }

                if (!discovered.TryGetValue(moduleId, out var module))
                {
                    validationProbe.Fail("template.missing_module", moduleId);
                    continue;
                }

                InitializeModule(context, module);
                discovered.Remove(moduleId);
            }

            foreach (var module in discovered.Values)
            {
                InitializeModule(context, module);
            }

            var expectedCount = 0;
            foreach (var moduleId in config.SelectedModules)
            {
                if (moduleId != "game_bootstrap" && moduleId != "validation_probe")
                {
                    expectedCount++;
                }
            }

            if (initializedModules.Count != expectedCount)
            {
                validationProbe.Fail(
                    "template.module_count",
                    $"Expected {expectedCount} initialized modules but found {initializedModules.Count}."
                );
            }

            validationProbe.Pass(
                "template.bootstrap_ready",
                $"UNITY_TEMPLATE_READY:{config.GameTitle}:{config.Genre}:{initializedModules.Count}"
            );
        }

        private void InitializeModule(GameContext context, IGameModule module)
        {
            try
            {
                module.Initialize(context);
                initializedModules.Add(module);
                validationProbe.Pass("template.module_initialized", module.ModuleId);
            }
            catch (Exception exception)
            {
                validationProbe.Fail(
                    "template.module_exception",
                    $"{module.ModuleId}: {exception.Message}"
                );
                Debug.LogException(exception, module as UnityEngine.Object);
            }
        }
    }
}

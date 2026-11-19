using System;
using UnityEngine;

namespace TeamIdle.GameTemplate.Core
{
    public interface IGeneratedFeatureModule
    {
        bool IsFeatureBound { get; }

        void BindGeneratedFeature(GeneratedFeatureBindingContext context);
    }

    // Implement this on the gameplay component that owns an upgradeable value.
    // Stat IDs are declared by each UpgradeDefinition rather than by weapon type.
    public interface IGameplayStatSource
    {
        bool TryGetGameplayStat(string statId, out float value);
    }

    public sealed class GeneratedFeatureBindingContext
    {
        public GeneratedFeatureBindingContext(
            GameObject player,
            Transform modules,
            Transform environment,
            Transform entities,
            Transform ui
        )
        {
            Player = player;
            Modules = modules;
            Environment = environment;
            Entities = entities;
            Ui = ui;
        }

        public GameObject Player { get; }

        public Transform Modules { get; }

        public Transform Environment { get; }

        public Transform Entities { get; }

        public Transform Ui { get; }

        public T GetModule<T>()
            where T : Component
        {
            return Modules == null ? null : Modules.GetComponentInChildren<T>(true);
        }
    }
}

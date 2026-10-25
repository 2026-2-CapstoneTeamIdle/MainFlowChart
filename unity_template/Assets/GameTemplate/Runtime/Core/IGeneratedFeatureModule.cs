using System;
using UnityEngine;

namespace TeamIdle.GameTemplate.Core
{
    public interface IGeneratedFeatureModule
    {
        bool IsFeatureBound { get; }

        void BindGeneratedFeature(GeneratedFeatureBindingContext context);
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

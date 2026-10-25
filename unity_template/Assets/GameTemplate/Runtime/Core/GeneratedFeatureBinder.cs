using System;
using UnityEngine;

namespace TeamIdle.GameTemplate.Core
{
    [DefaultExecutionOrder(-900)]
    public sealed class GeneratedFeatureBinder : MonoBehaviour
    {
        [SerializeField]
        private GameObject player;

        [SerializeField]
        private Transform modules;

        [SerializeField]
        private Transform environment;

        [SerializeField]
        private Transform entities;

        [SerializeField]
        private Transform ui;

        public void Configure(
            GameObject nextPlayer,
            Transform nextModules,
            Transform nextEnvironment,
            Transform nextEntities,
            Transform nextUi
        )
        {
            player = nextPlayer;
            modules = nextModules;
            environment = nextEnvironment;
            entities = nextEntities;
            ui = nextUi;
        }

        private void Awake()
        {
            BindNow();
        }

        public int BindNow()
        {
            if (modules == null)
            {
                throw new InvalidOperationException("Generated feature modules root is missing.");
            }

            var boundCount = 0;
            var context = new GeneratedFeatureBindingContext(
                player,
                modules,
                environment,
                entities,
                ui
            );
            foreach (var behaviour in modules.GetComponentsInChildren<MonoBehaviour>(true))
            {
                if (behaviour is not IGeneratedFeatureModule feature)
                {
                    continue;
                }

                feature.BindGeneratedFeature(context);
                if (!feature.IsFeatureBound)
                {
                    throw new InvalidOperationException(
                        $"Generated feature did not bind itself: {behaviour.GetType().Name}"
                    );
                }

                Debug.Log($"UNITY_GENERATED_FEATURE_BOUND:{behaviour.GetType().Name}");
                boundCount++;
            }

            return boundCount;
        }
    }
}

using System;
using TeamIdle.GameTemplate.Core;
using UnityEngine;

namespace TeamIdle.GameTemplate.SurvivorLike
{
    public enum UpgradeRarity
    {
        Common,
        Rare,
        Epic,
        Legendary,
    }

    public sealed class RaritySystemModule : GameModuleBehaviour
    {
        [SerializeField]
        private Vector4 weights = new(70f, 22f, 7f, 1f);
        public override string ModuleId => "rarity_system";

        public UpgradeRarity Roll()
        {
            var total =
                Mathf.Max(0f, weights.x)
                + Mathf.Max(0f, weights.y)
                + Mathf.Max(0f, weights.z)
                + Mathf.Max(0f, weights.w);
            var roll = UnityEngine.Random.Range(0f, total);
            if ((roll -= Mathf.Max(0f, weights.x)) < 0f)
                return UpgradeRarity.Common;
            if ((roll -= Mathf.Max(0f, weights.y)) < 0f)
                return UpgradeRarity.Rare;
            if ((roll -= Mathf.Max(0f, weights.z)) < 0f)
                return UpgradeRarity.Epic;
            return UpgradeRarity.Legendary;
        }

        protected override void OnInitialize(GameContext context) => context.Register(this);
    }

    [Serializable]
    public sealed class UpgradeDefinition
    {
        public string upgradeId = string.Empty;
        public string displayName = string.Empty;

        [TextArea]
        public string description = string.Empty;
    }
}

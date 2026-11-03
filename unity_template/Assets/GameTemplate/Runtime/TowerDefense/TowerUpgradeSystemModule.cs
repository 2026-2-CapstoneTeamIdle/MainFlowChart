using System;
using TeamIdle.GameTemplate.Common;
using TeamIdle.GameTemplate.Core;
using TeamIdle.GameTemplate.Prototype;
using UnityEngine;

namespace TeamIdle.GameTemplate.TowerDefense
{
    public sealed class TowerUpgradeSystemModule : GameModuleBehaviour
    {
        [SerializeField]
        private int baseUpgradeCost = 30;

        [SerializeField]
        private float costGrowth = 1.5f;

        [SerializeField]
        private float damageMultiplier = 1.25f;

        [SerializeField]
        private float attackRateMultiplier = 1.1f;

        [SerializeField]
        private float rangeBonus = 0.25f;

        private EconomySystemModule economy;

        public override string ModuleId => "tower_upgrade_system";
        public event Action<PrototypeTowerWeapon> Upgraded;

        public int GetUpgradeCost(PrototypeTowerWeapon tower)
        {
            return tower == null
                ? 0
                : Mathf.Max(
                    1,
                    Mathf.RoundToInt(baseUpgradeCost * Mathf.Pow(costGrowth, tower.Level - 1))
                );
        }

        public bool TryUpgrade(PrototypeTowerWeapon tower)
        {
            if (tower == null)
                return false;
            economy ??= FindFirstObjectByType<EconomySystemModule>();
            var cost = GetUpgradeCost(tower);
            if (economy == null || !economy.Spend(cost))
                return false;
            tower.Upgrade(damageMultiplier, attackRateMultiplier, rangeBonus);
            Upgraded?.Invoke(tower);
            return true;
        }

        protected override void OnInitialize(GameContext context)
        {
            context.TryGet(out economy);
            context.Register(this);
        }
    }
}

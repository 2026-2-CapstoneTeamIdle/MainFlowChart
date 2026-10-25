using TeamIdle.GameTemplate.SurvivorLike;
using UnityEngine;

namespace TeamIdle.GameTemplate.Prototype
{
    public sealed class PrototypeWingUpgradeApplier : MonoBehaviour
    {
        private UpgradeSelectionSystemModule upgrades;
        private TopDownMovementModule movement;
        private AutoTargetSystemModule autoTarget;

        private void Start()
        {
            upgrades = FindFirstObjectByType<UpgradeSelectionSystemModule>();
            movement = FindFirstObjectByType<TopDownMovementModule>();
            autoTarget = FindFirstObjectByType<AutoTargetSystemModule>();
            if (upgrades != null)
                upgrades.Selected += Apply;
        }

        private void OnDestroy()
        {
            if (upgrades != null)
                upgrades.Selected -= Apply;
        }

        private void Apply(UpgradeSelectionSystemModule.UpgradeChoice choice)
        {
            if (choice?.Upgrade == null)
                return;
            var multiplier = choice.Rarity switch
            {
                UpgradeRarity.Rare => 1.5f,
                UpgradeRarity.Epic => 2f,
                UpgradeRarity.Legendary => 3f,
                _ => 1f,
            };
            switch (choice.Upgrade.upgradeId)
            {
                case "wing-power" when autoTarget != null:
                    autoTarget.Damage += 5f * multiplier;
                    break;
                case "wing-speed" when movement != null:
                    movement.MoveSpeed += 0.5f * multiplier;
                    break;
                case "attack-speed" when autoTarget != null:
                    autoTarget.AttacksPerSecond += 0.2f * multiplier;
                    break;
                case "feather-count" when autoTarget != null:
                    autoTarget.ProjectileCount += Mathf.Max(1, Mathf.RoundToInt(multiplier));
                    break;
            }
        }
    }
}

using System.Collections.Generic;
using TeamIdle.GameTemplate.Common;
using UnityEngine;

namespace TeamIdle.GameTemplate.Prototype
{
    public sealed class PrototypeTowerBuildController : MonoBehaviour
    {
        [SerializeField]
        private int buildCost = 40;

        [SerializeField]
        private List<PrototypeTowerBuildSlot> slots = new();

        [SerializeField]
        private Projectile2D projectilePrefab;
        private EconomySystemModule economy;

        public int BuildCost => buildCost;
        public int BuiltTowerCount { get; private set; }

        private void Awake()
        {
            BindSlots();
        }

        public void Configure(Projectile2D prefab, IEnumerable<PrototypeTowerBuildSlot> buildSlots)
        {
            projectilePrefab = prefab;
            slots.Clear();
            slots.AddRange(buildSlots);
            BindSlots();
        }

        private void BindSlots()
        {
            foreach (var slot in slots)
            {
                if (slot != null)
                {
                    slot.Bind(this);
                }
            }
        }

        public bool TryBuild(PrototypeTowerBuildSlot slot)
        {
            if (slot == null || slot.IsOccupied || projectilePrefab == null)
            {
                return false;
            }

            economy ??= FindFirstObjectByType<EconomySystemModule>();
            if (economy == null || !economy.Spend(buildCost))
            {
                return false;
            }

            slot.MarkBuilt();
            slot.gameObject.AddComponent<PrototypeTowerWeapon>().Configure(projectilePrefab);
            BuiltTowerCount++;
            return true;
        }
    }
}

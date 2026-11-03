using System;
using System.Collections.Generic;
using TeamIdle.GameTemplate.Common;
using UnityEngine;

namespace TeamIdle.GameTemplate.Prototype
{
    [Serializable]
    public sealed class TowerBuildDefinition
    {
        public string towerTypeId = "basic";
        public int cost = 40;
        public float range = 4f;
        public float attacksPerSecond = 1.2f;
        public float damage = 12f;
        public Color color = new(0.25f, 0.8f, 1f);
    }

    public sealed class PrototypeTowerBuildController : MonoBehaviour
    {
        [SerializeField]
        private int buildCost = 40;

        [SerializeField]
        private List<PrototypeTowerBuildSlot> slots = new();

        [SerializeField]
        private List<TowerBuildDefinition> towerTypes = new();

        [SerializeField]
        private Projectile2D projectilePrefab;
        private EconomySystemModule economy;

        public IReadOnlyList<TowerBuildDefinition> AvailableTowerTypes => towerTypes;
        public string SelectedTowerTypeId { get; private set; } = "basic";
        public int BuildCost => GetSelectedDefinition()?.cost ?? buildCost;
        public int BuiltTowerCount { get; private set; }

        private void Awake()
        {
            EnsureDefaultTowerTypes();
            BindSlots();
        }

        public void Configure(Projectile2D prefab, IEnumerable<PrototypeTowerBuildSlot> buildSlots)
        {
            projectilePrefab = prefab;
            slots.Clear();
            slots.AddRange(buildSlots);
            EnsureDefaultTowerTypes();
            BindSlots();
        }

        public bool SelectTowerType(string towerTypeId)
        {
            if (towerTypes.Exists(item => item.towerTypeId == towerTypeId))
            {
                SelectedTowerTypeId = towerTypeId;
                return true;
            }

            return false;
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
            return TryBuild(slot, SelectedTowerTypeId);
        }

        public bool TryBuild(PrototypeTowerBuildSlot slot, string towerTypeId)
        {
            if (slot == null || slot.IsOccupied || projectilePrefab == null)
            {
                return false;
            }

            var definition = towerTypes.Find(item => item.towerTypeId == towerTypeId);
            if (definition == null)
                return false;

            economy ??= FindFirstObjectByType<EconomySystemModule>();
            if (economy == null || !economy.Spend(definition.cost))
            {
                return false;
            }

            slot.MarkBuilt(definition.color);
            slot.gameObject.AddComponent<PrototypeTowerWeapon>()
                .Configure(
                    projectilePrefab,
                    definition.towerTypeId,
                    definition.range,
                    definition.attacksPerSecond,
                    definition.damage
                );
            BuiltTowerCount++;
            return true;
        }

        private TowerBuildDefinition GetSelectedDefinition()
        {
            EnsureDefaultTowerTypes();
            return towerTypes.Find(item => item.towerTypeId == SelectedTowerTypeId);
        }

        private void EnsureDefaultTowerTypes()
        {
            if (towerTypes.Count > 0)
                return;
            towerTypes.Add(
                new TowerBuildDefinition
                {
                    towerTypeId = "basic",
                    cost = buildCost,
                    range = 4f,
                    attacksPerSecond = 1.2f,
                    damage = 12f,
                    color = new Color(0.25f, 0.8f, 1f),
                }
            );
            towerTypes.Add(
                new TowerBuildDefinition
                {
                    towerTypeId = "rapid",
                    cost = Mathf.Max(buildCost + 15, 1),
                    range = 3.5f,
                    attacksPerSecond = 2f,
                    damage = 7f,
                    color = new Color(1f, 0.65f, 0.2f),
                }
            );
        }
    }
}

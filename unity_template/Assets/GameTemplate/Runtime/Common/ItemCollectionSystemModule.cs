using System;
using System.Collections.Generic;
using System.Globalization;
using TeamIdle.GameTemplate.Core;
using UnityEngine;

namespace TeamIdle.GameTemplate.Common
{
    public sealed class ItemCollectionSystemModule : GameModuleBehaviour
    {
        private readonly Dictionary<string, int> amounts = new(StringComparer.Ordinal);
        private GameStateStoreModule stateStore;
        private SaveSystemModule saveSystem;

        public override string ModuleId => "item_collection_system";
        public int TotalCount { get; private set; }
        public event Action<string, int, int> Collected;
        public event Action<string, int> Changed;

        public int GetAmount(string itemId) =>
            !string.IsNullOrWhiteSpace(itemId) && amounts.TryGetValue(itemId, out var value)
                ? value
                : 0;

        public bool Collect(string itemId, int amount = 1)
        {
            if (string.IsNullOrWhiteSpace(itemId) || amount <= 0)
                return false;
            var next = GetAmount(itemId) + amount;
            amounts[itemId] = next;
            TotalCount += amount;
            Persist(itemId, next);
            Collected?.Invoke(itemId, amount, next);
            Changed?.Invoke(itemId, next);
            return true;
        }

        public bool TrySpend(string itemId, int amount)
        {
            if (string.IsNullOrWhiteSpace(itemId) || amount <= 0 || GetAmount(itemId) < amount)
                return false;
            var next = amounts[itemId] - amount;
            amounts[itemId] = next;
            TotalCount = Mathf.Max(0, TotalCount - amount);
            Persist(itemId, next);
            Changed?.Invoke(itemId, next);
            return true;
        }

        protected override void OnInitialize(GameContext context)
        {
            context.TryGet(out stateStore);
            context.TryGet(out saveSystem);
            ReloadFromStateStore();
            if (saveSystem != null)
                saveSystem.Loaded += ReloadFromStateStore;
            context.Register(this);
        }

        protected override void OnShutdown()
        {
            if (saveSystem != null)
                saveSystem.Loaded -= ReloadFromStateStore;
        }

        private void Persist(string itemId, int value)
        {
            stateStore?.SetInt($"inventory.{itemId}", value);
            stateStore?.SetInt("inventory.total", TotalCount);
        }

        private void ReloadFromStateStore()
        {
            if (stateStore == null)
                return;
            amounts.Clear();
            TotalCount = 0;
            foreach (var entry in stateStore.CreateSnapshot())
            {
                if (
                    !entry.key.StartsWith("inventory.", StringComparison.Ordinal)
                    || entry.key == "inventory.total"
                    || !int.TryParse(
                        entry.value,
                        NumberStyles.Integer,
                        CultureInfo.InvariantCulture,
                        out var value
                    )
                )
                    continue;
                var itemId = entry.key.Substring("inventory.".Length);
                amounts[itemId] = Mathf.Max(0, value);
                TotalCount += amounts[itemId];
            }
        }
    }
}

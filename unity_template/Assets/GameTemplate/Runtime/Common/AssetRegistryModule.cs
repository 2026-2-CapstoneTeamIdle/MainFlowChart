using System;
using System.Collections.Generic;
using TeamIdle.GameTemplate.Core;
using UnityEngine;

namespace TeamIdle.GameTemplate.Common
{
    public sealed class AssetRegistryModule : GameModuleBehaviour
    {
        [Serializable]
        private sealed class AssetEntry
        {
            public string assetId = string.Empty;
            public UnityEngine.Object asset;
        }

        [SerializeField]
        private List<AssetEntry> assets = new();
        private readonly Dictionary<string, UnityEngine.Object> lookup = new(
            StringComparer.Ordinal
        );
        public override string ModuleId => "asset_registry";

        public bool TryGet<T>(string assetId, out T asset)
            where T : UnityEngine.Object
        {
            if (lookup.TryGetValue(assetId, out var value) && value is T typedAsset)
            {
                asset = typedAsset;
                return true;
            }
            asset = null;
            return false;
        }

        protected override void OnInitialize(GameContext context)
        {
            lookup.Clear();
            foreach (var entry in assets)
                if (!string.IsNullOrWhiteSpace(entry.assetId) && entry.asset != null)
                    lookup[entry.assetId] = entry.asset;
            context.Register(this);
        }
    }
}

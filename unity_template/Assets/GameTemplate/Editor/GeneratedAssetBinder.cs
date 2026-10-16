using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using TeamIdle.GameTemplate.Common;
using UnityEditor;
using UnityEditor.U2D.Sprites;
using UnityEngine;

namespace TeamIdle.GameTemplate.Editor
{
    public static class GeneratedAssetBinder
    {
        public const string ManifestPath =
            "Assets/GameTemplate/Generated/AssetBindingManifest.json";
        public const string ReportPath = "Assets/GameTemplate/Generated/AssetBindingReport.json";

        [Serializable]
        private sealed class BindingEntry
        {
            public string asset_id = string.Empty;
            public string asset_type = string.Empty;
            public string kind = string.Empty;
            public string unity_binding_key = string.Empty;
            public string unity_path = string.Empty;
            public bool required;
            public string sprite_mode = string.Empty;
            public int pixels_per_unit = 100;
            public bool transparent;
            public int tile_width;
            public int tile_height;
            public int columns;
            public int rows;
            public bool loop;
            public string unity_load_type = string.Empty;
            public string mixer_group = string.Empty;
            public float spatial_blend;
        }

        [Serializable]
        private sealed class BindingManifest
        {
            public string binding_version = string.Empty;
            public string contract_version = string.Empty;
            public string image_style = string.Empty;
            public List<BindingEntry> entries = new();
            public List<string> missing_required_asset_ids = new();
            public List<string> warnings = new();
        }

        [Serializable]
        private sealed class BindingReport
        {
            public List<string> imported_asset_ids = new();
            public List<string> scene_bound_asset_ids = new();
            public List<string> registry_asset_ids = new();
            public List<string> missing_required_asset_ids = new();
            public List<string> warnings = new();
        }

        public static void ImportAndConfigureAssets()
        {
            var manifest = LoadManifest();
            if (manifest == null)
            {
                return;
            }

            var warnings = new List<string>(manifest.warnings);
            foreach (var entry in manifest.entries)
            {
                AssetDatabase.ImportAsset(
                    entry.unity_path,
                    ImportAssetOptions.ForceSynchronousImport
                );
                if (entry.asset_type == "image")
                {
                    ConfigureTexture(entry, manifest.image_style, warnings);
                }
                else if (entry.asset_type == "sound")
                {
                    ConfigureAudio(entry);
                }
            }

            WriteReport(
                new BindingReport
                {
                    imported_asset_ids = manifest.entries.Select(item => item.asset_id).ToList(),
                    missing_required_asset_ids = manifest.missing_required_asset_ids,
                    warnings = warnings,
                }
            );
        }

        public static void BindSceneAssets(Transform moduleRoot, Transform generatedRoot)
        {
            var manifest = LoadManifest();
            if (manifest == null)
            {
                return;
            }

            var report = LoadReport();
            report.missing_required_asset_ids = manifest.missing_required_asset_ids;
            var registry = moduleRoot.GetComponentInChildren<AssetRegistryModule>(true);
            var registryAssets = new List<(string assetId, UnityEngine.Object asset)>();

            foreach (var entry in manifest.entries)
            {
                if (entry.asset_type == "image")
                {
                    var sprite = AssetDatabase.LoadAssetAtPath<Sprite>(entry.unity_path);
                    if (sprite == null)
                    {
                        report.warnings.Add($"Sprite import failed: {entry.asset_id}");
                        continue;
                    }

                    registryAssets.Add((entry.asset_id, sprite));
                    if (BindSprite(entry.asset_id, sprite, generatedRoot))
                    {
                        report.scene_bound_asset_ids.Add(entry.asset_id);
                    }
                    BindGeneratedPrefab(entry.asset_id, sprite, report);
                }
                else if (entry.asset_type == "sound")
                {
                    var clip = AssetDatabase.LoadAssetAtPath<AudioClip>(entry.unity_path);
                    if (clip == null)
                    {
                        report.warnings.Add($"Audio import failed: {entry.asset_id}");
                        continue;
                    }

                    registryAssets.Add((entry.asset_id, clip));
                    CreateAudioSource(entry, clip, generatedRoot, report);
                }
            }

            if (registry != null)
            {
                PopulateRegistry(registry, registryAssets);
                report.registry_asset_ids = registryAssets.Select(item => item.assetId).ToList();
            }
            else if (registryAssets.Count > 0)
            {
                report.warnings.Add(
                    "AssetRegistryModule is not selected; direct scene bindings only."
                );
            }

            report.scene_bound_asset_ids = report.scene_bound_asset_ids.Distinct().ToList();
            WriteReport(report);
            Debug.Log(
                $"UNITY_ASSET_BINDINGS_OK:{registryAssets.Count}:"
                    + report.missing_required_asset_ids.Count
            );
        }

        private static BindingManifest LoadManifest()
        {
            if (!File.Exists(ManifestPath))
            {
                return null;
            }

            var manifest = JsonUtility.FromJson<BindingManifest>(File.ReadAllText(ManifestPath));
            if (manifest == null || manifest.binding_version != "1.0.0")
            {
                throw new InvalidOperationException("Unsupported asset binding manifest.");
            }
            return manifest;
        }

        private static BindingReport LoadReport()
        {
            if (!File.Exists(ReportPath))
            {
                return new BindingReport();
            }
            return JsonUtility.FromJson<BindingReport>(File.ReadAllText(ReportPath))
                ?? new BindingReport();
        }

        private static void ConfigureTexture(
            BindingEntry entry,
            string imageStyle,
            List<string> warnings
        )
        {
            if (AssetImporter.GetAtPath(entry.unity_path) is not TextureImporter importer)
            {
                warnings.Add($"Texture importer unavailable: {entry.asset_id}");
                return;
            }

            importer.textureType = TextureImporterType.Sprite;
            importer.spriteImportMode =
                entry.sprite_mode == "multiple"
                    ? SpriteImportMode.Multiple
                    : SpriteImportMode.Single;
            importer.spritePixelsPerUnit = Mathf.Max(1, entry.pixels_per_unit);
            importer.alphaIsTransparency = entry.transparent;
            importer.mipmapEnabled = false;
            importer.filterMode =
                imageStyle == "Pixel Art" ? FilterMode.Point : FilterMode.Bilinear;
            importer.SaveAndReimport();

            if (entry.sprite_mode == "multiple")
            {
                if (!SliceSpriteSheet(importer, entry, warnings))
                {
                    // A usable single sprite is safer than a Multiple-mode texture with no frames.
                    importer.spriteImportMode = SpriteImportMode.Single;
                    importer.SaveAndReimport();
                }
            }
        }

        private static bool SliceSpriteSheet(
            TextureImporter importer,
            BindingEntry entry,
            List<string> warnings
        )
        {
            if (
                entry.tile_width <= 0
                || entry.tile_height <= 0
                || entry.columns <= 0
                || entry.rows <= 0
            )
            {
                warnings.Add($"Invalid sprite grid; slicing skipped: {entry.asset_id}");
                return false;
            }

            var factories = new SpriteDataProviderFactories();
            factories.Init();
            var provider = factories.GetSpriteEditorDataProviderFromObject(importer);
            if (provider == null)
            {
                warnings.Add(
                    $"Sprite data provider unavailable; slicing aborted: {entry.asset_id}"
                );
                return false;
            }
            provider.InitSpriteEditorDataProvider();
            if (!SupportsFrameCreation(provider))
            {
                warnings.Add(
                    $"Sprite provider cannot create/delete frames; slicing aborted: {entry.asset_id}"
                );
                return false;
            }

            var rects = new List<SpriteRect>();
            for (var row = 0; row < entry.rows; row++)
            {
                for (var column = 0; column < entry.columns; column++)
                {
                    var index = row * entry.columns + column;
                    rects.Add(
                        new SpriteRect
                        {
                            name = $"{entry.asset_id}_{index}",
                            spriteID = GUID.Generate(),
                            rect = new Rect(
                                column * entry.tile_width,
                                (entry.rows - row - 1) * entry.tile_height,
                                entry.tile_width,
                                entry.tile_height
                            ),
                            alignment = SpriteAlignment.Center,
                            pivot = new Vector2(0.5f, 0.5f),
                        }
                    );
                }
            }

            provider.SetSpriteRects(rects.ToArray());
            var nameProvider = provider.GetDataProvider<ISpriteNameFileIdDataProvider>();
            if (nameProvider != null)
            {
                nameProvider.SetNameFileIdPairs(
                    rects
                        .Select(rect => new SpriteNameFileIdPair(rect.name, rect.spriteID))
                        .ToList()
                );
            }
            provider.Apply();
            importer.SaveAndReimport();
            return true;
        }

        private static bool SupportsFrameCreation(ISpriteEditorDataProvider provider)
        {
            // Sprite package versions expose this capability through different API surfaces.
            // Discover it without creating frames when the capability is unavailable.
            const string capabilityTypeName = "UnityEditor.U2D.Sprites.ISpriteFrameEditCapability";
            const string capabilityEnumName = "UnityEditor.U2D.Sprites.EEditCapability";
            var capabilityType = AppDomain
                .CurrentDomain.GetAssemblies()
                .Select(assembly => assembly.GetType(capabilityTypeName, false))
                .FirstOrDefault(type => type != null);
            var capabilityEnum = AppDomain
                .CurrentDomain.GetAssemblies()
                .Select(assembly => assembly.GetType(capabilityEnumName, false))
                .FirstOrDefault(type => type != null);
            if (capabilityType == null || capabilityEnum == null)
            {
                return false;
            }

            var getter = typeof(ISpriteEditorDataProvider)
                .GetMethods()
                .FirstOrDefault(method =>
                    method.Name == "GetDataProvider" && method.IsGenericMethodDefinition
                );
            var capabilityProvider = getter
                ?.MakeGenericMethod(capabilityType)
                .Invoke(provider, null);
            var editCapability = capabilityType
                .GetMethod("GetEditCapability")
                ?.Invoke(capabilityProvider, null);
            if (editCapability == null)
            {
                return false;
            }

            var requested = Enum.Parse(capabilityEnum, "CreateAndDeleteSprite");
            var hasCapability = editCapability
                .GetType()
                .GetMethod("HasCapability", new[] { capabilityEnum });
            return hasCapability?.Invoke(editCapability, new[] { requested }) as bool? ?? false;
        }

        private static void ConfigureAudio(BindingEntry entry)
        {
            if (AssetImporter.GetAtPath(entry.unity_path) is not AudioImporter importer)
            {
                return;
            }

            var settings = importer.defaultSampleSettings;
            settings.loadType = entry.unity_load_type switch
            {
                "streaming" => AudioClipLoadType.Streaming,
                "compressed_in_memory" => AudioClipLoadType.CompressedInMemory,
                _ => AudioClipLoadType.DecompressOnLoad,
            };
            settings.preloadAudioData = settings.loadType != AudioClipLoadType.Streaming;
            importer.defaultSampleSettings = settings;
            importer.SaveAndReimport();
        }

        private static bool BindSprite(string assetId, Sprite sprite, Transform generatedRoot)
        {
            var names = SceneObjectNames(assetId);
            var bound = false;
            foreach (var renderer in generatedRoot.GetComponentsInChildren<SpriteRenderer>(true))
            {
                if (names.Any(name => RendererNameMatches(renderer.name, name)))
                {
                    renderer.sprite = sprite;
                    bound = true;
                }
            }
            return bound;
        }

        private static string[] SceneObjectNames(string assetId) =>
            assetId switch
            {
                "player_sprite" or "platformer_player" => new[] { "Player" },
                "platformer_tileset" => new[] { "Ground", "Platform_" },
                "tower_sprite" => new[] { "Tower" },
                "card_frame" or "card_art" => new[] { "CardSlot_" },
                "novel_background" => new[] { "SceneBackground" },
                "novel_character" => new[] { "CharacterLeft", "CharacterRight" },
                "raising_character" => new[] { "Trainee" },
                "raising_room" => new[] { "Room" },
                _ => Array.Empty<string>(),
            };

        private static bool RendererNameMatches(string rendererName, string target) =>
            target.EndsWith("_", StringComparison.Ordinal)
                ? rendererName.StartsWith(target, StringComparison.Ordinal)
                : rendererName == target;

        private static void BindGeneratedPrefab(string assetId, Sprite sprite, BindingReport report)
        {
            var path = assetId switch
            {
                "enemy_sprite" =>
                    $"{PrefabSceneAssembler.GeneratedPrefabRoot}/SurvivorEnemy.prefab",
                "tower_enemy" => $"{PrefabSceneAssembler.GeneratedPrefabRoot}/TowerEnemy.prefab",
                "feather_projectile" =>
                    $"{PrefabSceneAssembler.GeneratedPrefabRoot}/FeatherProjectile.prefab",
                _ => string.Empty,
            };
            if (string.IsNullOrEmpty(path) || !File.Exists(path))
            {
                return;
            }

            var root = PrefabUtility.LoadPrefabContents(path);
            try
            {
                var renderer = root.GetComponentInChildren<SpriteRenderer>(true);
                if (renderer != null)
                {
                    renderer.sprite = sprite;
                    PrefabUtility.SaveAsPrefabAsset(root, path);
                    report.scene_bound_asset_ids.Add(assetId);
                }
            }
            finally
            {
                PrefabUtility.UnloadPrefabContents(root);
            }
        }

        private static void CreateAudioSource(
            BindingEntry entry,
            AudioClip clip,
            Transform generatedRoot,
            BindingReport report
        )
        {
            var audioRoot = generatedRoot.Find("Audio");
            if (audioRoot == null)
            {
                audioRoot = new GameObject("Audio").transform;
                audioRoot.SetParent(generatedRoot, false);
            }
            var source = new GameObject(
                entry.asset_id,
                typeof(AudioSource)
            ).GetComponent<AudioSource>();
            source.transform.SetParent(audioRoot, false);
            source.clip = clip;
            source.loop = entry.loop;
            source.spatialBlend = Mathf.Clamp01(entry.spatial_blend);
            source.playOnAwake = entry.kind == "bgm" || entry.kind == "ambience";
            if (!string.IsNullOrWhiteSpace(entry.mixer_group))
            {
                report.warnings.Add(
                    $"Requested mixer group '{entry.mixer_group}' for {entry.asset_id}; "
                        + "routing requires an existing project AudioMixer."
                );
            }
            report.scene_bound_asset_ids.Add(entry.asset_id);
        }

        private static void PopulateRegistry(
            AssetRegistryModule registry,
            List<(string assetId, UnityEngine.Object asset)> values
        )
        {
            var serialized = new SerializedObject(registry);
            var entries = serialized.FindProperty("assets");
            entries.arraySize = values.Count;
            for (var index = 0; index < values.Count; index++)
            {
                var entry = entries.GetArrayElementAtIndex(index);
                entry.FindPropertyRelative("assetId").stringValue = values[index].assetId;
                entry.FindPropertyRelative("asset").objectReferenceValue = values[index].asset;
            }
            serialized.ApplyModifiedPropertiesWithoutUndo();
        }

        private static void WriteReport(BindingReport report)
        {
            File.WriteAllText(ReportPath, JsonUtility.ToJson(report, true));
            AssetDatabase.ImportAsset(ReportPath, ImportAssetOptions.ForceUpdate);
        }
    }
}

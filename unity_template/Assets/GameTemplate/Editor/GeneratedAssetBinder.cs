using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using TeamIdle.GameTemplate.Common;
using TeamIdle.GameTemplate.Prototype;
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
            public string audio_cue = string.Empty;
            public string surface_tile_path = string.Empty;
            public float surface_top_inset;
            public string surface_fill_path = string.Empty;
            public string scroll_tile_path = string.Empty;
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
                    ConfigureDerivedSprite(
                        entry.surface_tile_path,
                        entry,
                        manifest.image_style,
                        warnings
                    );
                    ConfigureDerivedSprite(
                        entry.surface_fill_path,
                        entry,
                        manifest.image_style,
                        warnings
                    );
                    ConfigureDerivedSprite(
                        entry.scroll_tile_path,
                        entry,
                        manifest.image_style,
                        warnings
                    );
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
                    var sprite = LoadEntrySprite(entry);
                    if (sprite == null)
                    {
                        report.warnings.Add($"Sprite import failed: {entry.asset_id}");
                        continue;
                    }

                    registryAssets.Add((entry.asset_id, sprite));
                    if (BindSprite(entry, sprite, generatedRoot, report.warnings))
                    {
                        report.scene_bound_asset_ids.Add(entry.asset_id);
                    }
                    BindGeneratedPrefab(entry, sprite, report);
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

        // Derived single sprites staged by the Python applicator next to the validated asset:
        // tileset surface/fill tiles (so platforms never depend on sprite-sheet slicing) and
        // the mirrored, seamlessly repeatable stage background.
        private static void ConfigureDerivedSprite(
            string path,
            BindingEntry entry,
            string imageStyle,
            List<string> warnings
        )
        {
            if (string.IsNullOrEmpty(path))
            {
                return;
            }

            AssetDatabase.ImportAsset(path, ImportAssetOptions.ForceSynchronousImport);
            if (AssetImporter.GetAtPath(path) is not TextureImporter importer)
            {
                warnings.Add($"Derived sprite importer unavailable: {path}");
                return;
            }

            importer.textureType = TextureImporterType.Sprite;
            importer.spriteImportMode = SpriteImportMode.Single;
            importer.spritePixelsPerUnit = Mathf.Max(1, entry.pixels_per_unit);
            importer.alphaIsTransparency = true;
            importer.mipmapEnabled = false;
            importer.wrapMode = TextureWrapMode.Clamp;
            var textureSettings = new TextureImporterSettings();
            importer.ReadTextureSettings(textureSettings);
            textureSettings.spriteMeshType = SpriteMeshType.FullRect;
            importer.SetTextureSettings(textureSettings);
            importer.filterMode =
                imageStyle == "Pixel Art" ? FilterMode.Point : FilterMode.Bilinear;
            importer.SaveAndReimport();
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
            // Sliced and tiled draw modes (used to fit generated art to the planned object
            // size and to repeat ground tiles) need full-rect sprite meshes.
            var textureSettings = new TextureImporterSettings();
            importer.ReadTextureSettings(textureSettings);
            textureSettings.spriteMeshType = SpriteMeshType.FullRect;
            importer.SetTextureSettings(textureSettings);
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

        private static bool BindSprite(
            BindingEntry entry,
            Sprite sprite,
            Transform generatedRoot,
            List<string> warnings
        )
        {
            var names = SceneObjectNames(entry.asset_id);
            var bound = false;
            foreach (var renderer in generatedRoot.GetComponentsInChildren<SpriteRenderer>(true))
            {
                if (names.Any(name => RendererNameMatches(renderer.name, name)))
                {
                    if (entry.kind == "tileset")
                    {
                        var surface = LoadDerivedSprite(entry.surface_tile_path);
                        AssignTiledSurface(
                            renderer,
                            surface != null ? surface : sprite,
                            LoadDerivedSprite(entry.surface_fill_path),
                            surface != null ? entry.surface_top_inset : 0f
                        );
                    }
                    else if (entry.asset_id == StageBackgroundAssetId)
                    {
                        var repeatable = LoadDerivedSprite(entry.scroll_tile_path);
                        AssignScrollingBackground(
                            renderer,
                            repeatable != null ? repeatable : sprite,
                            generatedRoot
                        );
                    }
                    else
                    {
                        AssignSprite(renderer, sprite, entry);
                        if (GroundedAssetIds.Contains(entry.asset_id))
                        {
                            ReportGroundedAlignment(renderer, warnings);
                        }
                    }
                    bound = true;
                }
            }
            return bound;
        }

        private const string StageBackgroundAssetId = "stage_background";
        private const float SideViewBackgroundParallax = 0.25f;

        private static Sprite LoadDerivedSprite(string path) =>
            string.IsNullOrEmpty(path) ? null : AssetDatabase.LoadAssetAtPath<Sprite>(path);

        private const float GroundedAlignmentTolerance = 0.05f;

        // Grounded art must start at the collider's bottom edge. Record any mismatch in the
        // binding report so placement problems can be traced to data or rendering.
        private static void ReportGroundedAlignment(SpriteRenderer renderer, List<string> warnings)
        {
            var collider = renderer.GetComponent<Collider2D>();
            if (collider == null)
            {
                return;
            }

            Physics2D.SyncTransforms();
            var visualBottom = renderer.bounds.min.y;
            var colliderBottom = collider.bounds.min.y;
            if (Mathf.Abs(visualBottom - colliderBottom) > GroundedAlignmentTolerance)
            {
                warnings.Add(
                    $"Visual bottom of {renderer.name} is {visualBottom - colliderBottom:F2} from "
                        + $"its collider (visual {visualBottom:F2}, collider {colliderBottom:F2}, "
                        + $"position {renderer.transform.position.y:F2}, "
                        + $"drawMode {renderer.drawMode}, size {renderer.size})"
                );
            }
        }

        // Tileset sheets are sliced into frames named "{asset_id}_{index}" from the top-left.
        // The top row holds the walkable ground surface tiles, so frame 0 is the surface tile.
        private static Sprite LoadEntrySprite(BindingEntry entry)
        {
            if (entry.sprite_mode == "multiple")
            {
                var frames = AssetDatabase
                    .LoadAllAssetsAtPath(entry.unity_path)
                    .OfType<Sprite>()
                    .ToList();
                var surface = frames.FirstOrDefault(frame => frame.name == $"{entry.asset_id}_0");
                if (surface != null)
                {
                    return surface;
                }
                if (frames.Count > 0)
                {
                    return frames[0];
                }
            }
            return AssetDatabase.LoadAssetAtPath<Sprite>(entry.unity_path);
        }

        private const string SurfaceTilesName = "SurfaceTiles";
        private const string SurfaceFillName = "SurfaceFill";
        private const float MaximumSurfaceTopInset = 0.6f;

        // Ground and platforms are a 1x1-unit placeholder stretched to the platform size and
        // their colliders were sized from it. The object, its scale and its colliders are
        // left untouched: its own renderer is hidden and child renderers repeat the tiles.
        //
        // The surface tile has sky and grass decorations above its solid ground edge
        // (topInset of its height). One surface row is placed so that solid edge lines up
        // with the collider top, letting decorations rise above it; thick ground is filled
        // below the surface row with the fill tile. Characters then stand on the ground
        // edge instead of floating over transparent sky.
        private static void AssignTiledSurface(
            SpriteRenderer renderer,
            Sprite surface,
            Sprite fill,
            float topInset
        )
        {
            var previous = renderer.sprite;
            var transform = renderer.transform;
            var scale = transform.localScale;
            if (
                previous == null
                || Mathf.Approximately(scale.x, 0f)
                || Mathf.Approximately(scale.y, 0f)
            )
            {
                renderer.sprite = surface;
                return;
            }

            var previousSize =
                renderer.drawMode == SpriteDrawMode.Simple
                    ? (Vector2)previous.bounds.size
                    : renderer.size;
            var world = new Vector2(
                previousSize.x * Mathf.Abs(scale.x),
                previousSize.y * Mathf.Abs(scale.y)
            );
            var tileHeight = surface.bounds.size.y;
            if (world.x <= 0f || world.y <= 0f || tileHeight <= 0f)
            {
                renderer.sprite = surface;
                return;
            }

            var solidFraction = 1f - Mathf.Clamp(topInset, 0f, MaximumSurfaceTopInset);
            // One surface row whose solid part covers the platform height. Thick ground keeps
            // the tile's own size and is filled below; without a fill tile the row grows.
            var tileScale = world.y / (tileHeight * solidFraction);
            if (fill != null)
            {
                tileScale = Mathf.Min(tileScale, 1f);
            }
            var rowHeight = tileHeight * tileScale;
            var solidHeight = rowHeight * solidFraction;
            var top = world.y * 0.5f;

            RemoveChild(transform, SurfaceTilesName);
            RemoveChild(transform, SurfaceFillName);
            CreateTiledChild(
                renderer,
                SurfaceTilesName,
                surface,
                tileScale,
                new Vector2(world.x, rowHeight),
                top - solidHeight + rowHeight * 0.5f
            );
            var fillHeight = world.y - solidHeight;
            if (fill != null && fillHeight > 0.001f)
            {
                CreateTiledChild(
                    renderer,
                    SurfaceFillName,
                    fill,
                    tileScale,
                    new Vector2(world.x, fillHeight),
                    -top + fillHeight * 0.5f
                );
            }

            renderer.sprite = surface;
            renderer.enabled = false;
        }

        // Child renderer with uniform world tile scale despite the parent's non-uniform scale.
        private static void CreateTiledChild(
            SpriteRenderer parentRenderer,
            string name,
            Sprite sprite,
            float tileScale,
            Vector2 worldSize,
            float worldCenterY
        )
        {
            var parent = parentRenderer.transform;
            var parentScale = parent.localScale;
            var child = new GameObject(name, typeof(SpriteRenderer));
            child.transform.SetParent(parent, false);
            child.transform.localPosition = new Vector3(0f, worldCenterY / parentScale.y, 0f);
            child.transform.localScale = new Vector3(
                tileScale / parentScale.x,
                tileScale / parentScale.y,
                1f
            );
            var renderer = child.GetComponent<SpriteRenderer>();
            renderer.sprite = sprite;
            renderer.drawMode = SpriteDrawMode.Tiled;
            renderer.tileMode = SpriteTileMode.Continuous;
            renderer.size = worldSize / tileScale;
            renderer.sortingLayerID = parentRenderer.sortingLayerID;
            renderer.sortingOrder = parentRenderer.sortingOrder;
        }

        private static void RemoveChild(Transform parent, string name)
        {
            var existing = parent.Find(name);
            if (existing != null)
            {
                UnityEngine.Object.DestroyImmediate(existing.gameObject);
            }
        }

        // The stage background must cover the whole camera route, not just the scene origin,
        // so it follows the camera and repeats horizontally with a slight parallax. Top-down
        // genres repeat it in both directions and keep it locked to the world.
        private static void AssignScrollingBackground(
            SpriteRenderer renderer,
            Sprite sprite,
            Transform generatedRoot
        )
        {
            renderer.sprite = sprite;
            var sideView =
                generatedRoot.GetComponentInChildren<PrototypePlatformerStageController>(true)
                != null;
            var scroller = renderer.GetComponent<PrototypeBackgroundScroller>();
            if (scroller == null)
            {
                scroller = renderer.gameObject.AddComponent<PrototypeBackgroundScroller>();
            }
            scroller.Configure(sideView ? SideViewBackgroundParallax : 1f, !sideView);
        }

        // Scene objects are built from a 1x1-unit placeholder scaled to their gameplay size,
        // and their colliders were sized from that placeholder. Swapping in generated art
        // must keep that footprint, so the new sprite is drawn inside the old visual box
        // (aspect-fit, or aspect-fill for backgrounds) through SpriteRenderer.size instead of
        // changing the transform scale, which would also resize colliders and child anchors.
        // Objects standing on the ground. Their art is generated bottom-anchored and may be
        // wider than the collider, so it is fitted to the object height and keeps its own
        // width. Keep in sync with GROUNDED_OBJECT_IDS in game_pipeline/asset_specs.py.
        private static readonly HashSet<string> GroundedAssetIds = new(StringComparer.Ordinal)
        {
            "platformer_player",
            "platformer_enemy",
            "platformer_hazard",
            "platformer_checkpoint",
            "platformer_goal",
        };

        private static void AssignSprite(SpriteRenderer renderer, Sprite sprite, BindingEntry entry)
        {
            var kind = entry.kind;
            var previous = renderer.sprite;
            if (kind == "tileset" || previous == null)
            {
                renderer.sprite = sprite;
                return;
            }

            var scale = renderer.transform.localScale;
            var previousSize =
                renderer.drawMode == SpriteDrawMode.Simple
                    ? (Vector2)previous.bounds.size
                    : renderer.size;
            var box = new Vector2(
                previousSize.x * Mathf.Abs(scale.x),
                previousSize.y * Mathf.Abs(scale.y)
            );
            var natural = (Vector2)sprite.bounds.size;
            renderer.sprite = sprite;
            if (
                box.x <= 0f
                || box.y <= 0f
                || natural.x <= 0f
                || natural.y <= 0f
                || Mathf.Approximately(scale.x, 0f)
                || Mathf.Approximately(scale.y, 0f)
            )
            {
                return;
            }

            var fit =
                kind == "background" ? Mathf.Max(box.x / natural.x, box.y / natural.y)
                : GroundedAssetIds.Contains(entry.asset_id) ? box.y / natural.y
                : Mathf.Min(box.x / natural.x, box.y / natural.y);
            renderer.drawMode = SpriteDrawMode.Sliced;
            renderer.size = new Vector2(
                natural.x * fit / Mathf.Abs(scale.x),
                natural.y * fit / Mathf.Abs(scale.y)
            );
        }

        // Keep in sync with game_pipeline/scene_visual_assets.py, which requests these images.
        private static string[] SceneObjectNames(string assetId) =>
            assetId switch
            {
                "player_sprite" or "platformer_player" => new[] { "Player" },
                "platformer_tileset" => new[] { "Ground", "Platform_" },
                "platformer_enemy" => new[] { "PatrolEnemy_" },
                "platformer_hazard" => new[] { "Hazard_" },
                "platformer_collectible" => new[] { "Collectible_" },
                "platformer_checkpoint" => new[] { "Checkpoint_" },
                "platformer_goal" => new[] { "StageGoal" },
                "stage_background" => new[] { "Background" },
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

        private static void BindGeneratedPrefab(
            BindingEntry entry,
            Sprite sprite,
            BindingReport report
        )
        {
            var path = entry.asset_id switch
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
                    AssignSprite(renderer, sprite, entry);
                    PrefabUtility.SaveAsPrefabAsset(root, path);
                    report.scene_bound_asset_ids.Add(entry.asset_id);
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
                audioRoot = new GameObject("Audio", typeof(GeneratedAudioCuePlayer)).transform;
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
            // GeneratedAudioCuePlayer starts each sound on its gameplay cue instead of on awake.
            source.playOnAwake = false;
            if (!string.IsNullOrEmpty(entry.audio_cue))
            {
                audioRoot
                    .GetComponent<GeneratedAudioCuePlayer>()
                    .AddBinding(
                        entry.audio_cue,
                        source,
                        entry.kind == "bgm" || entry.kind == "ambience"
                    );
            }
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

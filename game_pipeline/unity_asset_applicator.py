"""Stage validated generated assets in a mutable Unity project."""

from __future__ import annotations

import hashlib
import io
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from PIL import Image, ImageDraw

from game_pipeline.asset_specs import classify_sound_cue
from mainflow.ArtifactManager import ArtifactManager
from mainflow.contracts import (
    CONTRACT_VERSION,
    AssetBindingEntry,
    AssetBindingManifest,
    AssetGenerationItem,
    AssetGenerationRequest,
    ImageDraft,
    ImageValidationResult,
    SoundDraft,
    SoundValidationResult,
)


@dataclass(frozen=True)
class UnityAssetApplicationResult:
    """Files and IDs produced while staging validated assets."""

    manifest: AssetBindingManifest
    manifest_path: Path
    applied_image_asset_ids: list[str]
    applied_sound_asset_ids: list[str]
    suppressed_placeholder_image_asset_ids: list[str]


class UnityAssetApplicator:
    """Copy validated artifacts and describe deterministic Unity bindings."""

    UNITY_PROJECT_ROOT = Path("game/unity_project")
    GENERATED_ASSET_ROOT = Path("Assets/GameTemplate/Generated/AppliedAssets")
    MANIFEST_PATH = Path("Assets/GameTemplate/Generated/AssetBindingManifest.json")
    REBUILD_REQUEST_PATH = Path("Assets/GameTemplate/Generated/GenerationRequest.json")
    _SAFE_ID = re.compile(r"[^A-Za-z0-9_.-]+")
    _IMAGE_EXTENSIONS: ClassVar[set[str]] = {"png", "jpg", "jpeg", "tga", "psd"}
    _SOUND_EXTENSIONS: ClassVar[set[str]] = {"wav", "ogg", "mp3", "aiff", "aif"}

    def __init__(self, manager: ArtifactManager) -> None:
        self.manager = manager

    def apply(
        self,
        project_id: str,
        image_request: AssetGenerationRequest,
        sound_request: AssetGenerationRequest,
        image_draft: ImageDraft,
        sound_draft: SoundDraft,
        image_validation: ImageValidationResult,
        sound_validation: SoundValidationResult,
        *,
        include_unvalidated_drafts: bool = False,
        exclude_placeholder_images: bool = False,
        skip_image_application: bool = False,
    ) -> UnityAssetApplicationResult:
        project_root = self.manager.resolve_project_path(project_id, self.UNITY_PROJECT_ROOT)
        if not (project_root / "ProjectSettings/ProjectVersion.txt").is_file():
            raise FileNotFoundError(f"Generated Unity project is missing: {project_root}")

        entries: list[AssetBindingEntry] = []
        warnings: list[str] = []
        # Suppressed images are generated but deliberately left out of Unity, so the
        # required-asset and final image checks waive them instead of failing.
        suppressed_placeholder_image_ids: set[str] = set()
        if skip_image_application:
            image_assets, image_ids = [], set()
            suppressed_placeholder_image_ids = {
                str(asset["asset_id"]) for asset in image_draft["assets"]
            }
            warnings.append(
                "Image application is disabled; generated images stay in generated/images and "
                "Unity keeps its primitive visuals."
            )
        elif exclude_placeholder_images and "generator=placeholder" in image_draft["notes"]:
            image_assets, image_ids = [], set()
            suppressed_placeholder_image_ids = {
                str(asset["asset_id"]) for asset in image_draft["assets"]
            }
            warnings.append(
                "Placeholder image assets were intentionally not applied; Unity keeps its "
                "clean primitive visuals until a real image backend is configured."
            )
        else:
            image_assets, image_ids = self._application_selection(
                "image",
                image_draft,
                image_validation,
                include_unvalidated_drafts,
                warnings,
            )
        sound_assets, sound_ids = self._application_selection(
            "sound",
            sound_draft,
            sound_validation,
            include_unvalidated_drafts,
            warnings,
        )
        applied_images = self._stage_assets(
            project_id,
            "image",
            image_request,
            image_assets,
            image_ids,
            entries,
            warnings,
        )
        applied_sounds = self._stage_assets(
            project_id,
            "sound",
            sound_request,
            sound_assets,
            sound_ids,
            entries,
            warnings,
        )

        applied_ids = set(applied_images) | set(applied_sounds)
        required_items = [
            item
            for request in (image_request, sound_request)
            for item in request["assets"]
            if item["required"]
        ]
        missing_required = sorted(
            item["asset_id"]
            for item in required_items
            if item["asset_id"] not in applied_ids
            and item["asset_id"] not in suppressed_placeholder_image_ids
        )
        if missing_required:
            warnings.append("Required assets not applied: " + ", ".join(missing_required))

        manifest: AssetBindingManifest = {
            "binding_version": "1.0.0",
            "contract_version": CONTRACT_VERSION,
            "image_style": image_request["image_style"],
            "entries": sorted(entries, key=lambda item: (item["asset_type"], item["asset_id"])),
            "missing_required_asset_ids": missing_required,
            "suppressed_placeholder_image_asset_ids": sorted(suppressed_placeholder_image_ids),
            "warnings": warnings,
        }
        manifest_relative = self.UNITY_PROJECT_ROOT / self.MANIFEST_PATH
        manifest_path = self._write_mutable(
            project_id,
            manifest_relative,
            (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        )
        # The first Unity validation builds the scene before the parallel image/sound branches
        # finish and deletes its original request marker. Recreate the marker so the next Unity
        # open (including visual validation) imports the new files and rebinds the scene/prefabs.
        self._write_mutable(
            project_id,
            self.UNITY_PROJECT_ROOT / self.REBUILD_REQUEST_PATH,
            (
                json.dumps(
                    {
                        "reason": "validated_assets_applied",
                        "asset_ids": sorted(applied_ids),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n"
            ).encode("utf-8"),
        )
        return UnityAssetApplicationResult(
            manifest=manifest,
            manifest_path=manifest_path,
            applied_image_asset_ids=applied_images,
            applied_sound_asset_ids=applied_sounds,
            suppressed_placeholder_image_asset_ids=sorted(suppressed_placeholder_image_ids),
        )

    @classmethod
    def _application_selection(
        cls,
        asset_type: str,
        draft: ImageDraft | SoundDraft,
        validation: ImageValidationResult | SoundValidationResult,
        include_unvalidated_drafts: bool,
        warnings: list[str],
    ) -> tuple[list[dict[str, Any]], set[str]]:
        selected = cls._selected_assets(draft, validation)
        selected_ids = set(validation["validated_asset_ids"])
        if not include_unvalidated_drafts:
            return selected, selected_ids

        draft_assets = [dict(asset) for asset in draft["assets"]]
        draft_ids = {str(asset["asset_id"]) for asset in draft_assets}
        unvalidated = sorted(draft_ids - selected_ids)
        if unvalidated:
            warnings.append(
                "Diagnostic project includes generated but unvalidated "
                f"{asset_type} assets: " + ", ".join(unvalidated)
            )
        return draft_assets, draft_ids

    @staticmethod
    def _selected_assets(
        draft: ImageDraft | SoundDraft,
        validation: ImageValidationResult | SoundValidationResult,
    ) -> list[dict[str, Any]]:
        manifest = validation.get("validated_assets")
        # Legacy results can still be staged; final validation requires explicit selection.
        if manifest is None:
            return [dict(asset) for asset in draft["assets"]]
        if (
            manifest["contract_version"] != CONTRACT_VERSION
            or manifest["manifest_version"] != "1.0.0"
        ):
            raise ValueError("Unsupported validated asset manifest")
        assets = manifest["assets"]
        ids = [asset["asset_id"] for asset in assets]
        if len(ids) != len(set(ids)) or set(ids) != set(validation["validated_asset_ids"]):
            raise ValueError("Validated asset manifest IDs are inconsistent")
        return [dict(asset) for asset in assets]

    def _stage_assets(
        self,
        project_id: str,
        asset_type: str,
        request: AssetGenerationRequest,
        draft_assets: list[dict[str, Any]],
        validated_ids: set[str],
        entries: list[AssetBindingEntry],
        warnings: list[str],
    ) -> list[str]:
        if request["asset_type"] != asset_type:
            raise ValueError(f"Expected {asset_type} request, got {request['asset_type']}")
        requested = {item["asset_id"]: item for item in request["assets"]}
        drafted = {item["asset_id"]: item for item in draft_assets}
        applied: list[str] = []
        allowed_extensions = (
            self._IMAGE_EXTENSIONS if asset_type == "image" else self._SOUND_EXTENSIONS
        )
        unity_folder = "Images" if asset_type == "image" else "Sounds"

        for asset_id in sorted(validated_ids):
            item = requested.get(asset_id)
            asset = drafted.get(asset_id)
            if item is None or asset is None:
                warnings.append(f"Validated {asset_type} asset has no request/draft: {asset_id}")
                continue
            if asset.get("asset_type", asset_type) != asset_type:
                raise ValueError("Validated asset type mismatch")
            if asset["artifact"]["project_id"] != project_id:
                raise ValueError("Validated asset belongs to another project")
            if asset["unity_binding_key"] != item["unity_binding_key"]:
                warnings.append(f"Binding key mismatch prevented applying asset: {asset_id}")
                continue

            extension = str(asset["file_format"]).lower().lstrip(".")
            if extension not in allowed_extensions:
                warnings.append(
                    f"Unsupported {asset_type} format prevented applying {asset_id}: {extension}"
                )
                continue
            safe_id = self._SAFE_ID.sub("_", asset_id).strip("._") or "generated_asset"
            unity_path = (
                self.GENERATED_ASSET_ROOT / unity_folder / f"{safe_id}.{extension}"
            ).as_posix()
            content = self.manager.read_bytes(asset["artifact"])
            self._write_mutable(
                project_id,
                self.UNITY_PROJECT_ROOT / unity_path,
                content,
            )
            entry = self._binding_entry(item, unity_path)
            surface_path = self._stage_surface_tile(project_id, item, unity_path, content, warnings)
            if surface_path:
                entry["surface_tile_path"] = surface_path
            if asset_type == "sound" and not entry["audio_cue"]:
                warnings.append(f"No gameplay event matches sound; it will not play: {asset_id}")
            entries.append(entry)
            applied.append(asset_id)
        return applied

    def _stage_surface_tile(
        self,
        project_id: str,
        item: AssetGenerationItem,
        unity_path: str,
        content: bytes,
        warnings: list[str],
    ) -> str:
        """Copy the tileset's ground surface tile (top-left) as its own sprite file.

        Platforms repeat this one tile. Cutting it here keeps the tiled ground independent
        of Unity's sprite-sheet slicing, which is unavailable in some 2D Sprite package
        versions; without it Unity repeats the whole sheet instead of one tile. The
        validated sheet itself is still staged unchanged.
        """

        spec = item["generation_spec"]
        if item["asset_type"] != "image" or spec.get("kind") != "tileset":
            return ""
        tile_width = int(spec.get("tile_width", 0))
        tile_height = int(spec.get("tile_height", 0))
        try:
            if tile_width <= 0 or tile_height <= 0:
                raise ValueError("tileset has no tile size")
            with Image.open(io.BytesIO(content)) as sheet:
                if sheet.width < tile_width or sheet.height < tile_height:
                    raise ValueError("tileset is smaller than one tile")
                tile = sheet.convert("RGBA").crop((0, 0, tile_width, tile_height))
            tile = self._clear_surface_sky(tile)
            output = io.BytesIO()
            tile.save(output, format="PNG")
        except (OSError, ValueError) as error:
            warnings.append(f"Surface tile not extracted for {item['asset_id']}: {error}")
            return ""
        surface_path = unity_path.rsplit(".", 1)[0] + "_surface.png"
        self._write_mutable(
            project_id,
            self.UNITY_PROJECT_ROOT / surface_path,
            output.getvalue(),
        )
        return surface_path

    SURFACE_SKY_THRESHOLD = 40
    SURFACE_SKY_MAX_FRACTION = 0.5

    @classmethod
    def _clear_surface_sky(cls, tile: Image.Image) -> Image.Image:
        """Make the flat sky above the ground edge transparent.

        Tilesets are generated opaque, so the surface tile usually carries a band of
        background color above the grass. Left in place it draws a dark strip on top of
        every platform. Only regions connected to the two top corners are cleared, and
        the original tile is kept when the result does not look like sky above ground.
        """

        width, height = tile.size
        top_left = tile.getpixel((0, 0))
        top_right = tile.getpixel((width - 1, 0))
        if top_left[3] == 0 or top_right[3] == 0:
            return tile
        if max(abs(a - b) for a, b in zip(top_left[:3], top_right[:3], strict=True)) > (
            cls.SURFACE_SKY_THRESHOLD
        ):
            return tile

        cleared = tile.copy()
        for corner in ((0, 0), (width - 1, 0)):
            if cleared.getpixel(corner)[3]:
                ImageDraw.floodfill(cleared, corner, (0, 0, 0, 0), thresh=cls.SURFACE_SKY_THRESHOLD)
        alpha = cleared.getchannel("A")
        removed = alpha.histogram()[0] - tile.getchannel("A").histogram()[0]
        bottom_intact = all(alpha.getpixel((x, height - 1)) == 255 for x in range(width))
        if not bottom_intact or removed > width * height * cls.SURFACE_SKY_MAX_FRACTION:
            return tile
        return cleared

    @staticmethod
    def _binding_entry(item: AssetGenerationItem, unity_path: str) -> AssetBindingEntry:
        spec = item["generation_spec"]
        is_image = item["asset_type"] == "image"
        return {
            "asset_id": item["asset_id"],
            "asset_type": item["asset_type"],
            "kind": str(spec["kind"]),
            "unity_binding_key": item["unity_binding_key"],
            "unity_path": unity_path,
            "required": item["required"],
            "sprite_mode": str(spec.get("sprite_mode", "single")) if is_image else "",
            "pixels_per_unit": int(spec.get("pixels_per_unit", 100)) if is_image else 0,
            "transparent": bool(spec.get("transparent", False)) if is_image else False,
            "tile_width": int(spec.get("tile_width", 0)) if is_image else 0,
            "tile_height": int(spec.get("tile_height", 0)) if is_image else 0,
            "columns": int(spec.get("columns", 0)) if is_image else 0,
            "rows": int(spec.get("rows", 0)) if is_image else 0,
            "loop": bool(spec.get("loop", False)) if not is_image else False,
            "unity_load_type": str(spec.get("unity_load_type", "")) if not is_image else "",
            "mixer_group": str(spec.get("mixer_group", "")) if not is_image else "",
            "spatial_blend": float(spec.get("spatial_blend", 0.0)) if not is_image else 0.0,
            "audio_cue": (
                ""
                if is_image
                else str(spec.get("audio_cue", ""))
                or classify_sound_cue(item["purpose"], item["description"], str(spec["kind"]))
            ),
        }

    def _write_mutable(self, project_id: str, relative_path: Path, content: bytes) -> Path:
        target = self.manager.resolve_project_path(project_id, relative_path)
        expected_hash = None
        if target.is_file():
            expected_hash = hashlib.sha256(target.read_bytes()).hexdigest()
        return self.manager.write_project_file(
            project_id,
            relative_path,
            content,
            expected_sha256=expected_hash,
        )

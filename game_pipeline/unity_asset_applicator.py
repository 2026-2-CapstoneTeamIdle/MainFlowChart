"""Stage validated generated assets in a mutable Unity project."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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


class UnityAssetApplicator:
    """Copy validated artifacts and describe deterministic Unity bindings."""

    UNITY_PROJECT_ROOT = Path("game/unity_project")
    GENERATED_ASSET_ROOT = Path("Assets/GameTemplate/Generated/AppliedAssets")
    MANIFEST_PATH = Path("Assets/GameTemplate/Generated/AssetBindingManifest.json")
    _SAFE_ID = re.compile(r"[^A-Za-z0-9_.-]+")
    _IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "tga", "psd"}
    _SOUND_EXTENSIONS = {"wav", "ogg", "mp3", "aiff", "aif"}

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
    ) -> UnityAssetApplicationResult:
        project_root = self.manager.resolve_project_path(project_id, self.UNITY_PROJECT_ROOT)
        if not (project_root / "ProjectSettings/ProjectVersion.txt").is_file():
            raise FileNotFoundError(f"Generated Unity project is missing: {project_root}")

        entries: list[AssetBindingEntry] = []
        warnings: list[str] = []
        applied_images = self._stage_assets(
            project_id,
            "image",
            image_request,
            image_draft["assets"],
            set(image_validation["validated_asset_ids"]),
            entries,
            warnings,
        )
        applied_sounds = self._stage_assets(
            project_id,
            "sound",
            sound_request,
            sound_draft["assets"],
            set(sound_validation["validated_asset_ids"]),
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
            item["asset_id"] for item in required_items if item["asset_id"] not in applied_ids
        )
        if missing_required:
            warnings.append("Required assets not applied: " + ", ".join(missing_required))

        manifest: AssetBindingManifest = {
            "binding_version": "1.0.0",
            "contract_version": CONTRACT_VERSION,
            "image_style": image_request["image_style"],
            "entries": sorted(entries, key=lambda item: (item["asset_type"], item["asset_id"])),
            "missing_required_asset_ids": missing_required,
            "warnings": warnings,
        }
        manifest_relative = self.UNITY_PROJECT_ROOT / self.MANIFEST_PATH
        manifest_path = self._write_mutable(
            project_id,
            manifest_relative,
            (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        )
        return UnityAssetApplicationResult(
            manifest=manifest,
            manifest_path=manifest_path,
            applied_image_asset_ids=applied_images,
            applied_sound_asset_ids=applied_sounds,
        )

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
            entries.append(self._binding_entry(item, unity_path))
            applied.append(asset_id)
        return applied

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

"""Synchronize edited generated C# files with Unity project design metadata."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, cast


def sync(project_root: Path) -> None:
    root = project_root.resolve()
    design_path = root / "Assets/GameTemplate/Generated/GameLogicDesign.json"
    manifest_path = root / "GenerationManifest.json"
    design = _read_object(design_path)
    manifest = _read_object(manifest_path)

    design_modules = design.get("generated_modules")
    manifest_modules = manifest.get("generated_modules")
    if not isinstance(design_modules, list) or not isinstance(manifest_modules, list):
        raise ValueError("Generated module metadata is missing")

    manifest_by_id = {
        item.get("module_id"): item for item in manifest_modules if isinstance(item, dict)
    }
    for raw_module in design_modules:
        if not isinstance(raw_module, dict):
            raise ValueError("Generated module metadata must be an object")
        module = cast(dict[str, Any], raw_module)
        module_id = module.get("module_id")
        metadata = manifest_by_id.get(module_id)
        if not isinstance(module_id, str) or not isinstance(metadata, dict):
            raise ValueError(f"Manifest metadata is missing for {module_id}")
        relative_path = metadata.get("relative_path")
        if not isinstance(relative_path, str):
            raise ValueError(f"Generated source path is missing for {module_id}")
        source_path = (root / relative_path).resolve()
        source_path.relative_to(root)
        source = source_path.read_text(encoding="utf-8").replace("\r\n", "\n")
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
        module["source_code"] = source
        module["source_sha256"] = digest
        metadata["source_sha256"] = digest

    _write_object(design_path, design)
    _write_object(manifest_path, manifest)


def _read_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return cast(dict[str, Any], payload)


def _write_object(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_root", type=Path)
    arguments = parser.parse_args()
    sync(arguments.project_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

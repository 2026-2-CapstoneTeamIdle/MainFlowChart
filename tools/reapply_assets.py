"""Re-apply already generated assets to an existing generated Unity project.

Development helper for checking asset-binding changes without paying for new images:

1. Copies the current asset-binding scripts from ``unity_template`` into the project.
2. Stages the run's validated images and sounds again with ``UnityAssetApplicator``,
   which also writes the rebuild marker so Unity re-assembles the scene and rebinds
   the assets the next time the project is opened.

It does not rerun generation or validation, and the run's earlier validation reports
are not updated. Usage::

    uv run --locked python tools/reapply_assets.py --result-file workspace/last_result.json
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPOSITORY_ROOT))

from game_pipeline.unity_asset_applicator import UnityAssetApplicator
from mainflow.ArtifactManager import ArtifactManager

TEMPLATE_ROOT = REPOSITORY_ROOT / "unity_template"
# Scripts that assemble the scene and bind generated assets to it.
BINDING_SCRIPTS = (
    "Assets/GameTemplate/Editor/GeneratedAssetBinder.cs",
    "Assets/GameTemplate/Editor/PrefabSceneAssembler.cs",
    "Assets/GameTemplate/Runtime/Prototype/PrototypeBackgroundScroller.cs",
    "Assets/GameTemplate/Runtime/Prototype/PrototypeBackgroundScroller.cs.meta",
    "Assets/GameTemplate/Runtime/Prototype/PlatformerPrototypeActors.cs",
    "Assets/GameTemplate/Runtime/Platformer/PlatformerModules.cs",
)
STATE_KEYS = (
    "game_logic_draft",
    "image_asset_request",
    "sound_asset_request",
    "image_draft",
    "sound_draft",
    "image_validation_result",
    "sound_validation_result",
)


def reapply(result_file: Path) -> dict[str, Any]:
    result = json.loads(result_file.read_text(encoding="utf-8"))
    state = result.get("final_state") or {}
    missing = [key for key in ("project_id", *STATE_KEYS) if key not in state]
    if missing:
        raise SystemExit(
            f"{result_file} has no full asset run (missing: {', '.join(missing)}). "
            "Use the result of a normal run, not --game-test."
        )

    manager = ArtifactManager()
    project_id = state["project_id"]
    unity_root = manager.resolve_project_path(project_id, UnityAssetApplicator.UNITY_PROJECT_ROOT)
    if not (unity_root / "ProjectSettings/ProjectVersion.txt").is_file():
        raise SystemExit(f"Generated Unity project not found: {unity_root}")

    for relative in BINDING_SCRIPTS:
        source = TEMPLATE_ROOT / relative
        if source.is_file():
            destination = unity_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

    payloads = {key: manager.read_json(state[key]) for key in STATE_KEYS}
    application = UnityAssetApplicator(manager).apply(
        project_id,
        payloads["image_asset_request"],
        payloads["sound_asset_request"],
        payloads["image_draft"],
        payloads["sound_draft"],
        payloads["image_validation_result"],
        payloads["sound_validation_result"],
        include_unvalidated_drafts=payloads["game_logic_draft"]["status"] == "failed",
    )
    return {
        "project_id": project_id,
        "unity_project": str(unity_root),
        "applied_image_asset_ids": application.applied_image_asset_ids,
        "applied_sound_asset_ids": application.applied_sound_asset_ids,
        "surface_tiles": [
            entry["surface_tile_path"]
            for entry in application.manifest["entries"]
            if entry.get("surface_tile_path")
        ],
        "warnings": application.manifest["warnings"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--result-file",
        type=Path,
        default=REPOSITORY_ROOT / "workspace/last_result.json",
        help="Result JSON written by run_flow --result-file (default: workspace/last_result.json).",
    )
    report = reapply(parser.parse_args().result_file)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("Open the Unity project; it rebuilds the scene and rebinds the assets on load.")


if __name__ == "__main__":
    main()

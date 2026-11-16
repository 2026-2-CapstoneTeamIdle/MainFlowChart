"""Re-apply already generated assets to an existing generated Unity project.

Development helper for checking asset-binding changes without paying for new images:

1. Refreshes only the asset-binding scripts owned by this pipeline (the editor binder
   and the background scroller). Game logic scripts such as ``PrefabSceneAssembler.cs``
   or ``PlatformerModules.cs`` are never overwritten, because Codex or Claude Code may
   have implemented the game in them; when they differ from the template they are only
   listed in the report.
2. Stages the run's validated images and sounds again with ``UnityAssetApplicator``,
   using the same options as the workflow's ``apply_assets`` node
   (``MAINFLOW_APPLY_IMAGE_ASSETS`` and the placeholder exclusion for agent builders).
   It also writes the rebuild marker so Unity re-assembles the scene and rebinds the
   assets the next time the project is opened.

It does not rerun generation or validation, and the run's earlier validation reports
are not updated. Like ``run_flow``, it reads the repository ``.env`` without overriding
variables already set in the shell. Usage::

    uv run --locked python tools/reapply_assets.py --result-file workspace/last_result.json
"""

from __future__ import annotations

import argparse
import filecmp
import json
import shutil
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPOSITORY_ROOT))

from game_pipeline.unity_asset_applicator import UnityAssetApplicator
from mainflow.ArtifactManager import ArtifactManager
from mainflow.nodes.apply_assets import image_application_enabled, placeholder_images_excluded

TEMPLATE_ROOT = REPOSITORY_ROOT / "unity_template"
# Scripts that only bind generated assets; safe to refresh from the template.
BINDING_SCRIPTS = (
    "Assets/GameTemplate/Editor/GeneratedAssetBinder.cs",
    "Assets/GameTemplate/Runtime/Prototype/PrototypeBackgroundScroller.cs",
    "Assets/GameTemplate/Runtime/Prototype/PrototypeBackgroundScroller.cs.meta",
)
# Scene and gameplay scripts that also affect how assets look, but that agents may edit.
# They are reported when they differ from the template and never overwritten.
GAME_LOGIC_SCRIPTS = (
    "Assets/GameTemplate/Editor/PrefabSceneAssembler.cs",
    "Assets/GameTemplate/Runtime/Platformer/PlatformerModules.cs",
    "Assets/GameTemplate/Runtime/Prototype/PlatformerPrototypeActors.cs",
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


def sync_binding_scripts(unity_root: Path) -> dict[str, list[str]]:
    """Refresh binding scripts and list game logic scripts that differ from the template."""

    updated: list[str] = []
    for relative in BINDING_SCRIPTS:
        source = TEMPLATE_ROOT / relative
        if not source.is_file():
            continue
        destination = unity_root / relative
        if destination.is_file() and filecmp.cmp(source, destination, shallow=False):
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        updated.append(relative)

    differing = [
        relative
        for relative in GAME_LOGIC_SCRIPTS
        if (TEMPLATE_ROOT / relative).is_file()
        and (unity_root / relative).is_file()
        and not filecmp.cmp(TEMPLATE_ROOT / relative, unity_root / relative, shallow=False)
    ]
    return {"updated_binding_scripts": updated, "kept_game_logic_scripts": differing}


def application_options() -> dict[str, bool]:
    """The image options the workflow's apply_assets node uses."""

    return {
        "exclude_placeholder_images": placeholder_images_excluded(),
        "skip_image_application": not image_application_enabled(),
    }


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

    scripts = sync_binding_scripts(unity_root)
    options = application_options()
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
        **options,
    )
    return {
        "project_id": project_id,
        "unity_project": str(unity_root),
        **scripts,
        **options,
        "applied_image_asset_ids": application.applied_image_asset_ids,
        "applied_sound_asset_ids": application.applied_sound_asset_ids,
        "suppressed_image_asset_ids": application.suppressed_placeholder_image_asset_ids,
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
    load_dotenv(REPOSITORY_ROOT / ".env", override=False)
    report = reapply(parser.parse_args().result_file)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["skip_image_application"]:
        print("Images were not applied: set MAINFLOW_APPLY_IMAGE_ASSETS=on to apply them.")
    if report["kept_game_logic_scripts"]:
        print(
            "Kept project versions of game logic scripts that differ from the template; "
            "their template changes are not in this project."
        )
    print("Open the Unity project; it rebuilds the scene and rebinds the assets on load.")


if __name__ == "__main__":
    main()

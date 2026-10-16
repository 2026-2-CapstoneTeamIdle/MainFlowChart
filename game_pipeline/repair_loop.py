"""Bounded generation/Unity-validation loop. Tests and template are never model-editable."""

from copy import deepcopy
import os
from pathlib import Path
from typing import Any, Callable

from game_pipeline.unity_project_validator import UnityProjectValidator


def validate_and_repair(
    *,
    design,
    generation,
    request,
    generator,
    feature_generator,
    record: Callable[[str, Any], None],
    max_repairs: int = 2,
):
    if not 0 <= max_repairs <= 3:
        raise ValueError("MAINFLOW_GAME_MAX_REPAIRS must be between 0 and 3")
    validator = UnityProjectValidator(
        mode=os.environ.get("MAINFLOW_UNITY_VALIDATION_MODE", "required"),
        unity_editor=os.environ.get("UNITY_EDITOR_PATH"),
        timeout_seconds=int(os.environ.get("MAINFLOW_UNITY_VALIDATION_TIMEOUT_SECONDS", "300")),
    )
    root = generation.project_root
    for attempt in range(max_repairs + 1):
        draft = {
            "contract_version": design["contract_version"],
            "status": "generated",
            "engine": "Unity",
            "entry_scene": str(generation.entry_scene.relative_to(root.parent.parent).as_posix()),
            "required_image_asset_ids": [
                a["asset_id"]
                for a in design["game_spec"]["asset_requirements"]
                if a["asset_type"] == "image"
            ],
            "required_sound_asset_ids": [
                a["asset_id"]
                for a in design["game_spec"]["asset_requirements"]
                if a["asset_type"] == "sound"
            ],
        }
        outcome = validator.validate(root, draft, request)
        # Keep complete evidence on disk, but send only bounded diagnostic excerpts to the model.
        record(
            f"attempt_{attempt}",
            {
                "status": outcome.status,
                "checks": outcome.checks,
                "issues": outcome.issues,
                "unity_log": outcome.unity_log,
            },
        )
        if outcome.status == "passed":
            return design, generation
        codes = {issue["code"] for issue in outcome.issues}
        infra = (
            "No valid Unity Editor license",
            "Failed to activate",
            "already open",
            "Access is denied",
        )
        repairable = bool(codes & {"UNITY_BATCH_VALIDATION_FAILED", "UNITY_RUNTIME_TEST_FAILED"})
        if attempt == max_repairs or not repairable or any(s in outcome.unity_log for s in infra):
            raise RuntimeError(f"Unity validation failed after {attempt} repairs: {outcome.issues}")
        lines = outcome.unity_log.splitlines()
        diagnostic_lines = [
            line
            for line in lines
            if any(
                token in line for token in ("error CS", "Exception", "Error", "FAILED", "runtime.")
            )
        ]
        feedback = {
            "attempt": attempt,
            "issues": outcome.issues,
            "failed_checks": [c for c in outcome.checks if not c["passed"]],
            "diagnostics": "\n".join(diagnostic_lines)[:6000] or outcome.unity_log[-6000:],
        }
        modules = feature_generator.repair(design, feedback)
        revised = deepcopy(design)
        revised["generated_modules"] = modules
        # Preserve the failed project for inspection; never recursively delete user data.
        backup = root.with_name(f"{root.name}_failed_attempt_{attempt}")
        if backup.exists():
            raise FileExistsError(f"Refusing to overwrite failed attempt: {backup}")
        root.rename(backup)
        generation = generator.generate(
            revised,
            root,
            image_style=request["image_style"],
            mood_style=request["mood_style"],
            viewpoint=request["viewpoint"],
            reference_image=request["custom_image"],
        )
        design = revised
    raise AssertionError("unreachable")

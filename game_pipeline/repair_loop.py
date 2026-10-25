"""Bounded generation/Unity-validation loop. Tests and template are never model-editable."""

import os
import time
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

from game_pipeline.design_repairer import repair_design
from game_pipeline.game_failure_classifier import classify_failure
from game_pipeline.game_quality import evaluate_game_quality
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
    seen_signatures: dict[str, int] = {}
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
            if "design_v2" in design:
                threshold = float(os.environ.get("MAINFLOW_GAME_QUALITY_THRESHOLD", "80"))
                report = evaluate_game_quality(design, outcome.unity_log, threshold=threshold)
                revised = deepcopy(design)
                revised["quality_report"] = report
                design = revised
                record("quality_report", report)
                # Old/static validators do not emit telemetry. A real Play Mode
                # run does, and only that evidence can enforce the quality gate.
                if "UNITY_PLAYTEST_METRICS:" in outcome.unity_log and not report["passed"]:
                    raise RuntimeError(
                        f"Unity validation passed but objective quality score "
                        f"{report['score']} is below {report['threshold']}: {report['problems']}"
                    )
            return design, generation
        classification = classify_failure(outcome)
        record(f"attempt_{attempt}_classification", classification)
        seen_signatures[classification["signature"]] = (
            seen_signatures.get(classification["signature"], 0) + 1
        )
        if (
            attempt == max_repairs
            or classification["target"] == "infrastructure"
            or seen_signatures[classification["signature"]] > 2
        ):
            raise RuntimeError(f"Unity validation failed after {attempt} repairs: {outcome.issues}")
        target = classification["target"]
        if target in {"code", "binding", "test"}:
            if feature_generator is None or not design["generated_modules"]:
                raise RuntimeError(
                    f"Unity {target} validation failed, but there is no generated feature "
                    f"code to repair: {outcome.issues}"
                )
            diagnostic_lines = [
                line
                for line in outcome.unity_log.splitlines()
                if any(
                    token in line
                    for token in (
                        "error CS",
                        "Exception",
                        "Error",
                        "FAILED",
                        "runtime.",
                        "Tag:",
                        "CompareTag",
                    )
                )
            ]
            feedback = {
                "attempt": attempt,
                "repair_target": target,
                "failure_signature": classification["signature"],
                "issues": outcome.issues,
                "failed_checks": [c for c in outcome.checks if not c["passed"]],
                "diagnostics": "\n".join(diagnostic_lines)[:6000] or outcome.unity_log[-6000:],
            }
            modules = feature_generator.repair(design, feedback)
            revised = deepcopy(design)
            revised["generated_modules"] = modules
        else:
            if "design_v2" not in design:
                raise RuntimeError(
                    f"Unity {target} validation failed without design v2 repair data: "
                    f"{outcome.issues}"
                )
            revised, actions = repair_design(design, target)
            record(
                f"attempt_{attempt}_design_repair",
                {"target": target, "actions": actions},
            )
        # Preserve the failed project for inspection; never recursively delete user data.
        backup = _available_backup(root, attempt)
        _rename_with_retry(root, backup)
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


def _available_backup(root: Path, attempt: int) -> Path:
    """Choose a recoverable backup name without overwriting a previous run."""

    base = root.with_name(f"{root.name}_failed_attempt_{attempt}")
    if not base.exists():
        return base
    for suffix in range(1, 100):
        candidate = root.with_name(f"{root.name}_failed_attempt_{attempt}_{suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"Too many preserved failed attempts beside {root}")


def _rename_with_retry(root: Path, backup: Path, timeout_seconds: float = 15.0) -> None:
    """Preserve a failed Unity project after transient Windows handle release delays."""

    deadline = time.monotonic() + timeout_seconds
    delay = 0.1
    while True:
        try:
            root.rename(backup)
            return
        except PermissionError as error:
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Timed out preserving failed Unity project: {root} -> {backup}"
                ) from error
            time.sleep(delay)
            delay = min(delay * 1.5, 0.75)

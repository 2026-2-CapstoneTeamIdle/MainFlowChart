"""Classify Unity failures so the development loop repairs the right artifact."""

from __future__ import annotations

import hashlib
import re
from typing import Literal, TypedDict

from game_pipeline.unity_project_validator import UnityValidationOutcome

RepairTarget = Literal[
    "code",
    "scene",
    "level_plan",
    "balance_plan",
    "content_plan",
    "binding",
    "test",
    "infrastructure",
]


class FailureClassification(TypedDict):
    target: RepairTarget
    signature: str
    evidence: str


def classify_failure(outcome: UnityValidationOutcome) -> FailureClassification:
    """Return a stable repair target and signature for loop detection."""

    evidence = "\n".join(
        [*(issue["message"] for issue in outcome.issues), outcome.unity_log[-8000:]]
    )
    lowered = evidence.lower()
    codes = {issue["code"] for issue in outcome.issues}

    target: RepairTarget = "test"
    if codes & {"UNITY_EDITOR_NOT_FOUND", "UNITY_EDITOR_START_FAILED"} or any(
        token in lowered
        for token in ("no valid unity editor license", "failed to activate", "access is denied")
    ):
        target = "infrastructure"
    elif "error cs" in lowered or "compilation" in lowered or "compile" in lowered:
        target = "code"
    elif "required_feature_unbound" in lowered or "runtime.binding" in lowered:
        target = "binding"
    elif any(token in lowered for token in ("too narrow", "gap before", "step before", "route")):
        target = "level_plan"
    elif any(token in lowered for token in ("tuning", "stat", "damage mismatch", "speed mismatch")):
        target = "balance_plan"
    elif any(
        token in lowered for token in ("placement", "content count", "collectible_requirement")
    ):
        target = "content_plan"
    elif any(
        token in lowered
        for token in ("required_scene_object_missing", "fixture_missing", "scene assembly")
    ) or codes & {"UNITY_BATCH_VALIDATION_FAILED"}:
        target = "scene"

    normalized = re.sub(r"[A-Za-z]:\\[^\s|]+", "<path>", evidence)
    normalized = re.sub(r"\b\d+(?:\.\d+)?\b", "#", normalized)
    signature = hashlib.sha256(f"{target}:{normalized}".encode()).hexdigest()[:16]
    return {"target": target, "signature": signature, "evidence": evidence[-4000:]}

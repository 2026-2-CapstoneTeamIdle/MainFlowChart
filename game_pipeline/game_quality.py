"""Objective quality measurements for generated vertical slices."""

from __future__ import annotations

import json
import re

from mainflow.contracts import GameLogicDesign, GameQualityReport, PlaytestMetrics, QualityMetric
from game_pipeline.runtime_invariants import REQUIRED_CAUSAL_TRANSITIONS

_METRICS_MARKER = re.compile(r"UNITY_PLAYTEST_METRICS:(\{.*\})")
_SCENARIO_MARKER = re.compile(r"UNITY_VALIDATION_SCENARIO_OK:([^\r\n]+)")
_TRANSITION_MARKER = re.compile(r"UNITY_CAUSAL_TRANSITION_OK:([^\r\n]+)")
_VALIDATION_FAIL_MARKER = re.compile(r"VALIDATION_FAIL:([^\r\n]+)")


def parse_playtest_metrics(unity_log: str) -> PlaytestMetrics:
    marker_scenarios = _SCENARIO_MARKER.findall(unity_log)
    marker_failures = _VALIDATION_FAIL_MARKER.findall(unity_log)
    marker_transitions = _TRANSITION_MARKER.findall(unity_log)
    defaults: PlaytestMetrics = {
        "completed": "UNITY_RUNTIME_SMOKE_OK:" in unity_log,
        "elapsed_seconds": 0.0,
        "deaths": 0,
        "stuck_seconds": 0.0,
        "last_reached_zone": "",
        "failed_transition": "",
        "unused_requested_features": [],
        "passed_scenarios": marker_scenarios,
        "passed_transitions": marker_transitions,
        "validation_failures": marker_failures,
    }
    matches = _METRICS_MARKER.findall(unity_log)
    if not matches:
        return defaults
    try:
        payload = json.loads(matches[-1])
    except json.JSONDecodeError:
        defaults["failed_transition"] = "invalid_metrics_json"
        return defaults
    for key in defaults:
        if key in payload:
            defaults[key] = payload[key]
    defaults["passed_scenarios"] = list(
        dict.fromkeys([*marker_scenarios, *defaults["passed_scenarios"]])
    )
    defaults["passed_transitions"] = list(
        dict.fromkeys([*marker_transitions, *defaults["passed_transitions"]])
    )
    defaults["unused_requested_features"] = list(
        dict.fromkeys(defaults["unused_requested_features"])
    )
    defaults["validation_failures"] = list(
        dict.fromkeys([*marker_failures, *defaults["validation_failures"]])
    )
    return defaults


def evaluate_game_quality(
    design: GameLogicDesign,
    unity_log: str,
    *,
    threshold: float = 80.0,
) -> GameQualityReport:
    """Score only observable contract/scene/runtime evidence (maximum 100)."""

    telemetry = parse_playtest_metrics(unity_log)
    bundle = design["design_v2"]
    level = bundle["level_plan"]
    validation = bundle["validation_plan"]
    required_features = set(validation["required_feature_bindings"])
    unused = set(telemetry["unused_requested_features"])
    validation_failures = telemetry["validation_failures"]
    bound_ratio = (
        1.0
        if not required_features
        else 1 - len(unused & required_features) / len(required_features)
    )
    effective_bound_ratio = 0.0 if validation_failures else bound_ratio
    expected_scenarios = {item["scenario_id"] for item in validation["scenarios"]}
    passed_scenarios = set(telemetry["passed_scenarios"])
    scenario_ratio = (
        len(expected_scenarios & passed_scenarios) / len(expected_scenarios)
        if expected_scenarios
        else 1.0
    )
    expected_transitions = set(REQUIRED_CAUSAL_TRANSITIONS[level["genre"]])
    passed_transitions = set(telemetry["passed_transitions"])
    transition_ratio = (
        len(expected_transitions & passed_transitions) / len(expected_transitions)
        if expected_transitions
        else 1.0
    )
    playtest_ratio = min(scenario_ratio, transition_ratio)
    zones = level["zones"]
    zone_ratio = min(1.0, len(zones) / 3) if level["genre"] == "Platformer" else 1.0
    placements = sum(
        len(zone[collection])
        for zone in zones
        for collection in ("enemies", "hazards", "collectibles")
    )
    archetype_count = sum(
        len(bundle["content_plan"][collection])
        for collection in ("enemies", "obstacles", "rewards")
    )
    planned_content_count = sum(
        item["count"]
        for collection in ("enemies", "obstacles", "rewards")
        for item in bundle["content_plan"][collection]
    )
    density_basis = (
        placements if level["genre"] == "Platformer" else max(placements, planned_content_count)
    )
    density_ratio = min(1.0, density_basis / 12)
    diversity_ratio = min(1.0, archetype_count / 6)
    content_ratio = (density_ratio + diversity_ratio) / 2
    presentation = bundle["presentation_plan"]
    presentation_ratio = min(
        1.0,
        (len(presentation["ui_screens"]) + len(presentation["feedback_cues"])) / 7,
    )
    difficulties = [zone["difficulty"] for zone in zones]
    progression_ok = (
        bool(difficulties) and difficulties == sorted(difficulties) and len(set(difficulties)) > 1
    )
    if not progression_ok and len(bundle["balance_plan"]["difficulty_curve"]) >= 2:
        progression_ok = True

    raw = [
        (
            "feature_binding",
            20.0 * effective_bound_ratio,
            20.0,
            bound_ratio == 1.0 and not validation_failures,
            f"{len(required_features - unused)}/{len(required_features)} requested features bound; "
            f"validation failures={len(validation_failures)}",
        ),
        (
            "playtest_completion",
            20.0 * playtest_ratio,
            20.0,
            telemetry["completed"] and scenario_ratio == 1.0 and transition_ratio == 1.0,
            f"{len(passed_scenarios & expected_scenarios)}/{len(expected_scenarios)} scenarios and "
            f"{len(passed_transitions & expected_transitions)}/{len(expected_transitions)} "
            "causal transitions passed",
        ),
        (
            "level_structure",
            15.0 * zone_ratio,
            15.0,
            zone_ratio == 1.0,
            f"{len(zones)} planned zones",
        ),
        (
            "content_density",
            15.0 * content_ratio,
            15.0,
            density_ratio >= 1.0 and diversity_ratio >= 1.0,
            f"{density_basis} placed or runtime-planned actors across "
            f"{archetype_count} content archetypes",
        ),
        (
            "presentation",
            10.0 * presentation_ratio,
            10.0,
            presentation_ratio >= 1.0,
            f"{len(presentation['ui_screens'])} screens, {len(presentation['feedback_cues'])} feedback cues",
        ),
        (
            "difficulty_progression",
            10.0 if progression_ok else 0.0,
            10.0,
            progression_ok,
            f"zone difficulties={difficulties}",
        ),
        (
            "requested_mechanics_used",
            10.0 if not unused else 0.0,
            10.0,
            not unused,
            "unused=" + (", ".join(sorted(unused)) or "none"),
        ),
    ]
    metrics: list[QualityMetric] = [
        {
            "metric_id": metric_id,
            "score": round(score, 2),
            "maximum": maximum,
            "passed": passed,
            "evidence": evidence,
        }
        for metric_id, score, maximum, passed, evidence in raw
    ]
    score = round(sum(metric["score"] for metric in metrics), 2)
    problems = [
        metric["metric_id"] + ": " + metric["evidence"]
        for metric in metrics
        if not metric["passed"]
    ]
    return {
        "report_version": "1.0.0",
        "score": score,
        "threshold": threshold,
        "passed": (
            score >= threshold
            and telemetry["completed"]
            and scenario_ratio == 1.0
            and transition_ratio == 1.0
            and not validation_failures
        ),
        "metrics": metrics,
        "problems": problems,
        "telemetry": telemetry,
    }

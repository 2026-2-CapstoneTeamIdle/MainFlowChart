"""Objective quality measurements for generated vertical slices."""

from __future__ import annotations

import json
import re

from mainflow.contracts import GameLogicDesign, GameQualityReport, PlaytestMetrics, QualityMetric

_METRICS_MARKER = re.compile(r"UNITY_PLAYTEST_METRICS:(\{.*\})")
_SCENARIO_MARKER = re.compile(r"UNITY_VALIDATION_SCENARIO_OK:([^\r\n]+)")


def parse_playtest_metrics(unity_log: str) -> PlaytestMetrics:
    defaults: PlaytestMetrics = {
        "completed": "UNITY_RUNTIME_SMOKE_OK:" in unity_log,
        "elapsed_seconds": 0.0,
        "deaths": 0,
        "stuck_seconds": 0.0,
        "last_reached_zone": "",
        "failed_transition": "",
        "unused_requested_features": [],
        "passed_scenarios": _SCENARIO_MARKER.findall(unity_log),
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
    defaults["passed_scenarios"] = list(dict.fromkeys(defaults["passed_scenarios"]))
    defaults["unused_requested_features"] = list(
        dict.fromkeys(defaults["unused_requested_features"])
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
    bound_ratio = (
        1.0
        if not required_features
        else 1 - len(unused & required_features) / len(required_features)
    )
    expected_scenarios = {item["scenario_id"] for item in validation["scenarios"]}
    passed_scenarios = set(telemetry["passed_scenarios"])
    scenario_ratio = (
        len(expected_scenarios & passed_scenarios) / len(expected_scenarios)
        if expected_scenarios
        else 1.0
    )
    zones = level["zones"]
    zone_ratio = min(1.0, len(zones) / 3) if level["genre"] == "Platformer" else 1.0
    placements = sum(
        len(zone[collection])
        for zone in zones
        for collection in ("enemies", "hazards", "collectibles")
    )
    density_ratio = min(1.0, placements / 12) if zones else 0.0
    archetype_count = sum(
        len(bundle["content_plan"][collection])
        for collection in ("enemies", "obstacles", "rewards")
    )
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

    raw = [
        (
            "feature_binding",
            20.0 * bound_ratio,
            20.0,
            bound_ratio == 1.0,
            f"{len(required_features - unused)}/{len(required_features)} requested features bound",
        ),
        (
            "playtest_completion",
            20.0 * scenario_ratio,
            20.0,
            telemetry["completed"] and scenario_ratio == 1.0,
            f"{len(passed_scenarios & expected_scenarios)}/{len(expected_scenarios)} scenarios passed",
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
            f"{placements} placements across {archetype_count} content archetypes",
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
        "passed": score >= threshold and telemetry["completed"],
        "metrics": metrics,
        "problems": problems,
        "telemetry": telemetry,
    }

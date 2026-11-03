"""Deterministic repairs for validated design documents.

The model may propose a design, but predictable geometry/count/range defects are
repaired here so a Unity runtime failure is not incorrectly sent to the C# agent.
"""

from __future__ import annotations

import re
from copy import deepcopy
from itertools import pairwise

from game_pipeline.design_v2 import validate_design_v2
from game_pipeline.game_failure_classifier import RepairTarget
from mainflow.contracts import GameLogicDesign


def repair_design(
    design: GameLogicDesign, target: RepairTarget, evidence: str = ""
) -> tuple[GameLogicDesign, list[str]]:
    revised = deepcopy(design)
    bundle = revised["design_v2"]
    actions: list[str] = []

    if target == "level_plan":
        level = bundle["level_plan"]
        minimum_width = level["minimum_landing_width"]
        platforms = sorted(
            [platform for zone in level["zones"] for platform in zone["platforms"]],
            key=lambda item: item["x"],
        )
        for platform in platforms:
            if platform["width"] < minimum_width:
                platform["width"] = minimum_width
                actions.append(f"widened {platform['platform_id']} to {minimum_width}")
        for previous, current in pairwise(platforms):
            maximum_y = previous["y"] + level["max_step_up"]
            if current["y"] > maximum_y:
                current["y"] = maximum_y
                actions.append(f"lowered {current['platform_id']} to reachable height")
            gap = current["x"] - current["width"] / 2 - (previous["x"] + previous["width"] / 2)
            if gap > level["max_horizontal_gap"]:
                previous["width"] += gap - level["max_horizontal_gap"]
                actions.append(f"extended {previous['platform_id']} to close route gap")

        # A runtime no-progress failure is stronger evidence than the generic jump
        # threshold. Bridge the actual gap around the stopped player even when it is
        # nominally below max_horizontal_gap (the collider/body can still be too wide).
        if "runtime.route_no_progress" in evidence.lower() and platforms:
            match = re.search(
                r"current=\(\s*(-?\d+(?:\.\d+)?)\s*,", evidence, re.IGNORECASE
            ) or re.search(r"best_x\s*=\s*(-?\d+(?:\.\d+)?)", evidence, re.IGNORECASE)
            stopped_x = float(match.group(1)) if match else None
            gaps = []
            for previous, current in pairwise(platforms):
                previous_right = previous["x"] + previous["width"] / 2
                current_left = current["x"] - current["width"] / 2
                gap = current_left - previous_right
                if gap > 0:
                    midpoint = (previous_right + current_left) / 2
                    gaps.append(
                        (
                            abs(midpoint - stopped_x) if stopped_x is not None else -gap,
                            gap,
                            previous,
                        )
                    )
            if gaps:
                _, gap, previous = min(gaps, key=lambda item: item[0])
                previous["width"] += gap + 0.35
                actions.append(
                    f"bridged runtime route gap after {previous['platform_id']} by {gap + 0.35:.2f}"
                )
            else:
                nearest = min(
                    platforms,
                    key=lambda item: abs(item["x"] - stopped_x) if stopped_x is not None else 0,
                )
                nearest["width"] += 0.75
                actions.append(
                    f"expanded {nearest['platform_id']} around runtime no-progress point"
                )

    if target == "balance_plan":
        for stat in bundle["balance_plan"]["stats"]:
            clamped = min(stat["maximum"], max(stat["minimum"], stat["initial"]))
            if clamped != stat["initial"]:
                stat["initial"] = clamped
                actions.append(f"clamped {stat['stat_id']} to {clamped}")

    if target == "content_plan":
        level = bundle["level_plan"]
        mapping = (("enemies", "enemies"), ("obstacles", "hazards"), ("rewards", "collectibles"))
        for definitions_key, placements_key in mapping:
            for definition in bundle["content_plan"][definitions_key]:  # type: ignore[literal-required]
                count = sum(
                    1
                    for zone in level["zones"]
                    for placement in zone[placements_key]  # type: ignore[literal-required]
                    if placement["archetype"] == definition["content_id"]
                )
                if definition["count"] != count:
                    definition["count"] = count
                    actions.append(f"synchronized {definition['content_id']} count to {count}")

    # Scene and binding failures are repaired by rebuilding the generated
    # project from the same validated documents; repository-owned templates
    # remain immutable to the model.
    if target in {"scene", "binding"}:
        actions.append(f"rebuilt generated scene for {target} failure")

    validate_design_v2(bundle)
    return revised, actions

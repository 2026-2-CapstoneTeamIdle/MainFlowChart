"""Stage-by-stage LLM refinement for the design_game_logic v2 documents."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from typing import Any, Literal, cast

from game_pipeline.design_v2 import build_design_v2, validate_design_v2
from game_pipeline.gemini_feature_generator import (
    GeminiApiClient,
    LocalAIJsonClient,
    StructuredJsonClient,
)
from mainflow.contracts import DesignV2Bundle, GameSpec

DesignProvider = Literal["deterministic", "local", "gemini"]
STAGE_ORDER = (
    "game_design",
    "system_design",
    "content_plan",
    "level_plan",
    "balance_plan",
    "presentation_plan",
    "validation_plan",
)
REVISION_STAGE = "level_plan_revision"

STAGE_ROLES = {
    "game_design": "game director: define the intended three-to-five minute player experience",
    "system_design": "systems designer: connect player, enemy, combat, progress, save, and events",
    "content_plan": "content designer: define concrete enemy, obstacle, reward, and goal data",
    "level_plan": "2D level designer: make a traversable zone/challenge/reward/checkpoint route",
    "balance_plan": "balance designer: provide bounded initial values and difficulty progression",
    "presentation_plan": "presentation designer: connect UI, feedback, camera, particles, and assets",
    "validation_plan": "critical playtest lead: find progression risks and specify automated checks",
}


class StagedDesignV2Planner:
    """Use seven small structured calls instead of one oversized generation request."""

    def __init__(
        self,
        client: StructuredJsonClient,
        provider: Literal["local", "gemini"],
    ) -> None:
        self.client = client
        self.provider = provider
        self.fallback_stages: list[str] = []

    def generate(self, game_spec: GameSpec, design_intent: str) -> DesignV2Bundle:
        self.fallback_stages.clear()
        fallback = build_design_v2(game_spec, design_intent)
        result = cast(DesignV2Bundle, {})
        for stage in STAGE_ORDER:
            baseline = fallback[stage]  # type: ignore[literal-required]
            context = {name: result[name] for name in STAGE_ORDER if name in result}
            try:
                response = self.client.generate_json(
                    self._prompt(stage, game_spec, design_intent, context, baseline),
                    _schema_for(baseline),
                )
                _require_same_shape(response, baseline, stage)
                result[stage] = response  # type: ignore[literal-required]
                if stage == "game_design" and response["target_play_minutes"] < 3:
                    raise ValueError("target_play_minutes must be at least 3")
                if stage in {"level_plan", "presentation_plan", "validation_plan"}:
                    validate_design_v2({**fallback, **result})
            except Exception:  # noqa: BLE001 - each optional LLM stage has a safe fallback
                result[stage] = baseline  # type: ignore[literal-required]
                self.fallback_stages.append(stage)

        if game_spec["genre"] == "Platformer":
            try:
                revised_level = self.client.generate_json(
                    self._revision_prompt(game_spec, design_intent, result),
                    _schema_for(result["level_plan"]),
                )
                _require_same_shape(revised_level, result["level_plan"], REVISION_STAGE)
                candidate = {**result, "level_plan": revised_level}
                validate_design_v2(cast(DesignV2Bundle, candidate))
                result["level_plan"] = revised_level  # type: ignore[typeddict-item]
            except Exception:  # noqa: BLE001 - retain the last validated level plan
                self.fallback_stages.append(REVISION_STAGE)
        validate_design_v2(result)
        return result

    @staticmethod
    def _revision_prompt(
        game_spec: GameSpec,
        design_intent: str,
        design: DesignV2Bundle,
    ) -> str:
        return (
            "You are a senior 2D platformer director revising only level_plan after a critical "
            "playtest review. Return only the complete level_plan JSON object required by the "
            "schema. Resolve every risk in validation_plan without removing the tutorial, "
            "challenge, or mastery zones. Keep all routes within movement limits, place every "
            "planned enemy/hazard/reward intentionally, keep spawn safe, and make the requested "
            "mechanic necessary to progress. Do not emit Markdown or C#.\n\n"
            f"USER_INTENT={design_intent}\n"
            f"GAME_SPEC={json.dumps(game_spec, ensure_ascii=False, separators=(',', ':'))}\n"
            f"DESIGN={json.dumps(design, ensure_ascii=False, separators=(',', ':'))}"
        )

    @staticmethod
    def _prompt(
        stage: str,
        game_spec: GameSpec,
        design_intent: str,
        upstream: Mapping[str, Any],
        baseline: Any,
    ) -> str:
        critique = (
            "Critique the upstream design for blocked progression, missing scene content, and "
            "unbound requested mechanics before writing executable playtest scenarios."
            if stage == "validation_plan"
            else "Keep every decision implementable by the supplied Unity 2D modules."
        )
        return (
            f"You are the {STAGE_ROLES[stage]}. Return only the JSON object required by the "
            "schema. Do not emit Markdown, C#, file paths, or commentary. Preserve every field "
            "and identifier from the safe baseline unless the user request requires a concrete "
            "improvement. For Platformer, keep at least three ordered zones (tutorial, challenge, "
            "mastery), landing widths >= minimum_landing_width, horizontal gaps <= "
            "max_horizontal_gap, and upward steps <= max_step_up. The requested mechanic must be "
            f"used by progression rather than decorative. {critique}\n\n"
            f"USER_INTENT={design_intent}\n"
            f"GAME_SPEC={json.dumps(game_spec, ensure_ascii=False, separators=(',', ':'))}\n"
            f"UPSTREAM={json.dumps(upstream, ensure_ascii=False, separators=(',', ':'))}\n"
            f"SAFE_BASELINE={json.dumps(baseline, ensure_ascii=False, separators=(',', ':'))}"
        )


def create_design_v2_planner_from_environment() -> StagedDesignV2Planner | None:
    provider = os.environ.get("MAINFLOW_DESIGN_V2_PROVIDER", "deterministic").strip().lower()
    if provider == "deterministic":
        return None
    if provider == "local":
        return StagedDesignV2Planner(LocalAIJsonClient.from_environment(), "local")
    if provider == "gemini":
        return StagedDesignV2Planner(GeminiApiClient.from_environment(), "gemini")
    raise ValueError(f"Unsupported MAINFLOW_DESIGN_V2_PROVIDER: {provider}")


def _schema_for(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        properties = {key: _schema_for(item) for key, item in value.items()}
        return {
            "type": "object",
            "additionalProperties": False,
            "required": list(properties),
            "properties": properties,
        }
    if isinstance(value, list):
        return {
            "type": "array",
            "items": _schema_for(value[0]) if value else {},
        }
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, (int, float)):
        return {"type": "number"}
    if value is None:
        return {"type": ["object", "null"]}
    return {"type": "string"}


def _require_same_shape(value: Any, baseline: Any, path: str) -> None:
    if isinstance(baseline, Mapping):
        if not isinstance(value, Mapping) or set(value) != set(baseline):
            raise ValueError(f"{path} does not match the required object shape")
        for key, baseline_item in baseline.items():
            _require_same_shape(value[key], baseline_item, f"{path}.{key}")
        return
    if isinstance(baseline, list):
        if not isinstance(value, list):
            raise TypeError(f"{path} must be an array")
        if baseline:
            for index, item in enumerate(value):
                exemplar = baseline[index] if index < len(baseline) else baseline[0]
                _require_same_shape(item, exemplar, f"{path}[{index}]")
        return
    if baseline is None:
        if value is not None and not isinstance(value, Mapping):
            raise ValueError(f"{path} must be an object or null")
        return
    if isinstance(baseline, bool):
        matches = isinstance(value, bool)
    elif isinstance(baseline, (int, float)):
        matches = not isinstance(value, bool) and isinstance(value, (int, float))
    else:
        matches = isinstance(value, str)
    if not matches:
        raise ValueError(f"{path} has the wrong value type")

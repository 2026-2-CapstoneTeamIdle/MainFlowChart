"""Optional LLM scene planner with strict validation and a deterministic fallback."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping
from typing import Any, Literal, cast

from game_pipeline.game_blueprint import build_game_blueprint
from game_pipeline.gemini_feature_generator import (
    GeminiApiClient,
    LocalAIJsonClient,
    StructuredJsonClient,
)
from mainflow.contracts import (
    BlueprintContentDirective,
    BlueprintEntity,
    BlueprintProgressionOption,
    GameBlueprint,
    GameSpec,
)

BlueprintProvider = Literal["deterministic", "local", "gemini"]
_HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{0,47}$")

# Keep this deliberately compact. The LLM proposes only presentation and content
# data; it never generates C#, Unity assets, package references, or file paths.
BLUEPRINT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "summary",
        "scene_width",
        "scene_height",
        "background_color_hex",
        "core_loop",
        "content",
        "entities",
        "progression_options",
        "ui_labels",
    ],
    "properties": {
        "summary": {"type": "string", "minLength": 8, "maxLength": 320},
        "scene_width": {"type": "number", "minimum": 20, "maximum": 48},
        "scene_height": {"type": "number", "minimum": 12, "maximum": 30},
        "background_color_hex": {"type": "string", "pattern": "^#[0-9A-Fa-f]{6}$"},
        "core_loop": {
            "type": "array",
            "minItems": 3,
            "maxItems": 6,
            "items": {"type": "string", "minLength": 1, "maxLength": 48},
        },
        "content": {
            "type": "array",
            "minItems": 3,
            "maxItems": 8,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["archetype", "count", "purpose"],
                "properties": {
                    "archetype": {"type": "string", "pattern": "^[a-z][a-z0-9_]{0,47}$"},
                    "count": {"type": "integer", "minimum": 1, "maximum": 50},
                    "purpose": {"type": "string", "minLength": 1, "maxLength": 80},
                },
            },
        },
        "entities": {
            "type": "array",
            "minItems": 3,
            "maxItems": 16,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "entity_id",
                    "display_name",
                    "archetype",
                    "position_x",
                    "position_y",
                    "scale_x",
                    "scale_y",
                    "color_hex",
                    "behavior_tags",
                ],
                "properties": {
                    "entity_id": {"type": "string", "pattern": "^[a-z][a-z0-9_]{0,47}$"},
                    "display_name": {"type": "string", "minLength": 1, "maxLength": 48},
                    "archetype": {"type": "string", "pattern": "^[a-z][a-z0-9_]{0,47}$"},
                    "position_x": {"type": "number", "minimum": -24, "maximum": 24},
                    "position_y": {"type": "number", "minimum": -14, "maximum": 14},
                    "scale_x": {"type": "number", "minimum": 0.1, "maximum": 4},
                    "scale_y": {"type": "number", "minimum": 0.1, "maximum": 4},
                    "color_hex": {"type": "string", "pattern": "^#[0-9A-Fa-f]{6}$"},
                    "behavior_tags": {
                        "type": "array",
                        "maxItems": 6,
                        "items": {"type": "string", "minLength": 1, "maxLength": 32},
                    },
                },
            },
        },
        "progression_options": {
            "type": "array",
            "maxItems": 8,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["option_id", "display_name", "description", "rarity"],
                "properties": {
                    "option_id": {"type": "string", "pattern": "^[a-z][a-z0-9_]{0,47}$"},
                    "display_name": {"type": "string", "minLength": 1, "maxLength": 48},
                    "description": {"type": "string", "minLength": 1, "maxLength": 100},
                    "rarity": {"type": "string", "enum": ["common", "rare", "epic", "legendary"]},
                },
            },
        },
        "ui_labels": {
            "type": "array",
            "minItems": 2,
            "maxItems": 10,
            "items": {"type": "string", "minLength": 1, "maxLength": 32},
        },
    },
}


class GameBlueprintPlanner:
    """Constrain an LLM to data that the existing Unity assembler can consume."""

    def __init__(self, client: StructuredJsonClient, provider: Literal["local", "gemini"]) -> None:
        self.client = client
        self.provider = provider

    def generate(
        self,
        game_spec: GameSpec,
        design_intent: str,
        *,
        variation_seed: str = "",
    ) -> GameBlueprint:
        fallback = build_game_blueprint(
            game_spec,
            design_intent,
            variation_seed=variation_seed,
        )
        response = self.client.generate_json(
            self._prompt(game_spec, design_intent, fallback, variation_seed),
            BLUEPRINT_SCHEMA,
        )
        return self._validate(response, fallback)

    @staticmethod
    def _prompt(
        game_spec: GameSpec,
        design_intent: str,
        fallback: GameBlueprint,
        variation_seed: str = "",
    ) -> str:
        return (
            "You are the scene planner for a Unity 2D prototype. Produce a concise game "
            "blueprint from the request. This is data only: do not write C#, instructions, "
            "file paths, assets, or Markdown. Preserve player_anchor and objective entities, "
            "and preserve the content archetypes from the fallback. You may improve positions, "
            "counts, names, presentation, landmarks, UI labels, and survivor progression. "
            "The runtime owns all behavior.\n\n"
            + json.dumps(
                {
                    "genre": game_spec["genre"],
                    "title": game_spec["title"],
                    "viewpoint": game_spec["viewpoint"],
                    "user_request": design_intent,
                    "variation_seed": variation_seed,
                    "features": [feature["description"] for feature in game_spec["features"]],
                    "fallback_blueprint": fallback,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )

    def _validate(self, response: Mapping[str, Any], fallback: GameBlueprint) -> GameBlueprint:
        try:
            content = _content(response["content"])
            entities = _entities(response["entities"])
            progression = _progression(response["progression_options"])
            core_loop = _strings(response["core_loop"], minimum=3, maximum=6, label="core_loop")
            ui_labels = _strings(response["ui_labels"], minimum=2, maximum=10, label="ui_labels")
            summary = _text(response["summary"], "summary", 8, 320)
            scene_width = _number(response["scene_width"], "scene_width", 20, 48)
            scene_height = _number(response["scene_height"], "scene_height", 12, 30)
            color = _color(response["background_color_hex"], "background_color_hex")
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"LLM game blueprint is invalid: {error}") from error

        required_content = {item["archetype"] for item in fallback["content"]}
        actual_content = {item["archetype"] for item in content}
        required_entities = {"player_anchor", "objective"}
        actual_entities = {item["archetype"] for item in entities}
        if not required_content.issubset(actual_content):
            raise ValueError("LLM game blueprint omitted a required content archetype")
        if not required_entities.issubset(actual_entities):
            raise ValueError("LLM game blueprint omitted player_anchor or objective")

        digest = hashlib.sha256(
            json.dumps(response, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:16]
        genre_prefix = fallback["blueprint_id"].rsplit("-", maxsplit=1)[0]
        return {
            "blueprint_version": "1.0.0",
            "blueprint_id": f"{genre_prefix}-{digest}",
            "source": self.provider,
            "title": fallback["title"],
            "summary": summary,
            "scene_width": scene_width,
            "scene_height": scene_height,
            "background_color_hex": color,
            "core_loop": core_loop,
            "content": content,
            "entities": entities,
            "progression_options": progression,
            "ui_labels": ui_labels,
        }


def create_blueprint_planner_from_environment() -> GameBlueprintPlanner | None:
    """Return a planner only when explicitly enabled; default runs stay offline and fast."""

    provider = os.environ.get("MAINFLOW_BLUEPRINT_PROVIDER", "deterministic").strip().lower()
    if provider == "deterministic":
        return None
    if provider == "local":
        return GameBlueprintPlanner(LocalAIJsonClient.from_environment(), "local")
    if provider == "gemini":
        return GameBlueprintPlanner(GeminiApiClient.from_environment(), "gemini")
    raise ValueError("MAINFLOW_BLUEPRINT_PROVIDER must be 'deterministic', 'local', or 'gemini'")


def _content(value: Any) -> list[BlueprintContentDirective]:
    if not isinstance(value, list) or not 3 <= len(value) <= 8:
        raise ValueError("content must contain 3 to 8 entries")
    result: list[BlueprintContentDirective] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError("content item must be an object")
        result.append(
            {
                "archetype": _identifier(item.get("archetype"), "content archetype"),
                "count": int(_number(item.get("count"), "content count", 1, 50)),
                "purpose": _text(item.get("purpose"), "content purpose", 1, 80),
            }
        )
    if len({item["archetype"] for item in result}) != len(result):
        raise ValueError("content archetypes must be unique")
    return result


def _entities(value: Any) -> list[BlueprintEntity]:
    if not isinstance(value, list) or not 3 <= len(value) <= 16:
        raise ValueError("entities must contain 3 to 16 entries")
    result: list[BlueprintEntity] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError("entity must be an object")
        tags = _strings(item.get("behavior_tags"), minimum=0, maximum=6, label="behavior_tags")
        result.append(
            {
                "entity_id": _identifier(item.get("entity_id"), "entity_id"),
                "display_name": _text(item.get("display_name"), "display_name", 1, 48),
                "archetype": _identifier(item.get("archetype"), "entity archetype"),
                "position_x": _number(item.get("position_x"), "position_x", -24, 24),
                "position_y": _number(item.get("position_y"), "position_y", -14, 14),
                "scale_x": _number(item.get("scale_x"), "scale_x", 0.1, 4),
                "scale_y": _number(item.get("scale_y"), "scale_y", 0.1, 4),
                "color_hex": _color(item.get("color_hex"), "color_hex"),
                "behavior_tags": tags,
            }
        )
    if len({item["entity_id"] for item in result}) != len(result):
        raise ValueError("entity_id values must be unique")
    return result


def _progression(value: Any) -> list[BlueprintProgressionOption]:
    if not isinstance(value, list) or len(value) > 8:
        raise ValueError("progression_options must contain at most 8 entries")
    result: list[BlueprintProgressionOption] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError("progression option must be an object")
        rarity = item.get("rarity")
        if rarity not in {"common", "rare", "epic", "legendary"}:
            raise ValueError("progression rarity is invalid")
        result.append(
            {
                "option_id": _identifier(item.get("option_id"), "option_id"),
                "display_name": _text(item.get("display_name"), "option display_name", 1, 48),
                "description": _text(item.get("description"), "option description", 1, 100),
                "rarity": cast(Literal["common", "rare", "epic", "legendary"], rarity),
            }
        )
    return result


def _strings(value: Any, *, minimum: int, maximum: int, label: str) -> list[str]:
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise ValueError(f"{label} must contain {minimum} to {maximum} entries")
    return [_text(item, label, 1, 48) for item in value]


def _text(value: Any, label: str, minimum: int, maximum: int) -> str:
    if not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum:
        raise ValueError(f"{label} must be a {minimum} to {maximum} character string")
    return value.strip()


def _identifier(value: Any, label: str) -> str:
    text = _text(value, label, 1, 48)
    if not _IDENTIFIER.fullmatch(text):
        raise ValueError(f"{label} is invalid")
    return text


def _number(value: Any, label: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number")
    number = float(value)
    if not minimum <= number <= maximum:
        raise ValueError(f"{label} is outside its safe range")
    return number


def _color(value: Any, label: str) -> str:
    color = _text(value, label, 7, 7)
    if not _HEX_COLOR.fullmatch(color):
        raise ValueError(f"{label} must be #RRGGBB")
    return color.upper()

"""Versioned, repository-derived context for generated C#; never model-invented APIs."""

from pathlib import Path
import re
from typing import Any

from game_pipeline.project_context_index import (
    build_project_context_index,
    compact_api_contract,
    retrieve_prompt_api_contract,
)


def build_feature_contract() -> dict[str, Any]:
    runtime = Path(__file__).resolve().parent.parent / "unity_template/Assets/GameTemplate/Runtime"
    structured_index = build_project_context_index(runtime)
    types = {
        "Core/GameModuleBehaviour.cs": "GameModuleBehaviour",
        "Core/IGeneratedFeatureModule.cs": "GeneratedFeatureBindingContext",
        "Common/PresentationAndFlow.cs": "InputAdapterModule",
        "Platformer/PlatformerModules.cs": "PlatformerMovementModule",
    }
    sources = {}
    for file, name in types.items():
        source = (runtime / file).read_text(encoding="utf-8")
        match = re.search(r"public (?:abstract |sealed )?class " + name + r"\b", source)
        if match:
            start = source.index("{", match.end())
            depth = 1
            end = start + 1
            while depth and end < len(source):
                depth += (source[end] == "{") - (source[end] == "}")
                end += 1
            sources[name] = source[match.start() : end]
    return {
        "version": "2.0.0",
        "engine": "Unity 6 / C# / Physics2D",
        "binding": {"target": "context.Player", "modules": "context.GetModule<T>()"},
        "runtime_api_sources": sources,
        "structured_api_index": compact_api_contract(structured_index),
        "ownership": {
            "horizontal_velocity": "PlatformerMovementModule owns velocity.x each FixedUpdate",
            "jump": "PlatformerMovementModule consumes buffered ConfirmPressed",
            "extension": "Do not duplicate movement. Coordinate with existing update order.",
        },
        "constraints": [
            "Never reference TestInputEnabled, TestMovement or UNITY_* validation markers in generated code.",
            "Do not invent APIs, layers, tags, assets, packages or scene objects.",
            "Never use CompareTag or GameObject.tag; generated projects define no custom tags.",
            "Exclude the player's own collider in wall and ground detection.",
            "Use ForceMode2D and linearVelocity; restore gravity/state on exit and disable.",
            "Null-check dependencies. No behavior before initialization and binding.",
        ],
        "acceptance": {
            "executed": [
                "Unity compilation",
                "scene assembly",
                "Play Mode exception smoke test",
                "generated feature binding",
                "finite player position",
                "platformer horizontal input causes displacement",
            ],
            "not_covered": "Arbitrary feature semantics require additional independent scenario tests.",
        },
    }


def build_generation_contract(
    selected_module_ids: list[str] | None = None,
    *,
    requirement_text: str = "",
    max_module_types: int = 6,
    max_dependency_types: int = 6,
) -> dict[str, Any]:
    """Return a compact allow-list for small models instead of full runtime source files."""

    runtime = Path(__file__).resolve().parent.parent / "unity_template/Assets/GameTemplate/Runtime"
    structured = retrieve_prompt_api_contract(
        build_project_context_index(runtime),
        selected_module_ids=selected_module_ids,
        requirement_text=requirement_text,
        max_module_types=max_module_types,
        max_dependency_types=max_dependency_types,
    )
    return {
        "contract_version": "2.0.0",
        **structured,
        "unity_2d_allow_list": [
            "Rigidbody2D.linearVelocity",
            "Rigidbody2D.gravityScale",
            "Rigidbody2D.AddForce(Vector2, ForceMode2D)",
            "Physics2D.Raycast",
            "Physics2D.OverlapCircleAll",
            "Collider2D",
            "BoxCollider2D",
            "CircleCollider2D",
            "GameObject",
            "GameObject.AddComponent<T>()",
            "SpriteRenderer",
            "Sprite.Create",
            "Texture2D.whiteTexture",
            "RaycastHit2D",
            "Transform",
            "Transform.SetParent",
            "Vector2",
            "Mathf",
            "Time",
        ],
        "ownership_rules": [
            "Do not recreate base movement, jumping, health, or another selected module.",
            "A generated module implements only its one requested feature.",
            "Store dependencies in private fields during BindGeneratedFeature.",
            "Never invent a member that is absent from project_types[type].public_api.",
            "Never use CompareTag or GameObject.tag; identify objects through bound references and components.",
        ],
    }

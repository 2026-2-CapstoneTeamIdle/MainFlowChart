"""Versioned, repository-derived context for generated C#; never model-invented APIs."""

from pathlib import Path
import re
from typing import Any


def build_feature_contract() -> dict[str, Any]:
    runtime = Path(__file__).resolve().parent.parent / "unity_template/Assets/GameTemplate/Runtime"
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
        "version": "1.0.0",
        "engine": "Unity 6 / C# / Physics2D",
        "binding": {"target": "context.Player", "modules": "context.GetModule<T>()"},
        "runtime_api_sources": sources,
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


def build_generation_contract() -> dict[str, Any]:
    """Return a compact allow-list for small models instead of full runtime source files."""

    return {
        "contract_version": "1.1.0",
        "project_types": {
            "GameModuleBehaviour": {
                "namespace": "TeamIdle.GameTemplate.Core",
                "members": [
                    "bool IsInitialized { get; }",
                    "string ModuleId { get; }",
                    "protected override void OnInitialize(GameContext context)",
                ],
            },
            "GeneratedFeatureBindingContext": {
                "namespace": "TeamIdle.GameTemplate.Core",
                "members": [
                    "GameObject Player { get; }",
                    "Transform Environment { get; }",
                    "Transform Entities { get; }",
                    "Transform Ui { get; }",
                    "T GetModule<T>() where T : Component",
                ],
                "scope": "The variable named context exists only inside BindGeneratedFeature.",
            },
            "InputAdapterModule": {
                "namespace": "TeamIdle.GameTemplate.Common",
                "members": [
                    "Vector2 Movement { get; }",
                    "bool ConfirmPressed { get; }",
                    "bool CancelPressed { get; }",
                ],
            },
            "PlatformerMovementModule": {
                "namespace": "TeamIdle.GameTemplate.Platformer",
                "members": [
                    "string ModuleId { get; }",
                    "void Bind(Rigidbody2D body, Transform groundCheck = null)",
                ],
                "ownership": "Already implements ordinary horizontal movement and jumping.",
            },
        },
        "unity_2d_allow_list": [
            "Rigidbody2D.linearVelocity",
            "Rigidbody2D.gravityScale",
            "Rigidbody2D.AddForce(Vector2, ForceMode2D)",
            "Physics2D.Raycast",
            "Physics2D.OverlapCircleAll",
            "Collider2D",
            "RaycastHit2D",
            "Transform",
            "Vector2",
            "Mathf",
            "Time",
        ],
        "ownership_rules": [
            "Do not recreate base movement, jumping, health, or another selected module.",
            "A generated module implements only its one requested feature.",
            "Store dependencies in private fields during BindGeneratedFeature.",
            "Never invent a member that is absent from project_types.",
            "Never use CompareTag or GameObject.tag; identify objects through bound references and components.",
        ],
    }

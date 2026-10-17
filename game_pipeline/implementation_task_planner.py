"""Build an executable task DAG for the game-development stage."""

from __future__ import annotations

from typing import Literal

from mainflow.contracts import GameLogicDesign, ImplementationTask, ImplementationTaskPlan


def build_implementation_tasks(
    design: GameLogicDesign,
    *,
    time_budget_seconds: int = 1_800,
) -> ImplementationTaskPlan:
    if not 60 <= time_budget_seconds <= 3_600:
        raise ValueError("Game development time budget must be between 60 and 3600 seconds")

    tasks: list[ImplementationTask] = [
        _task(
            "design-review",
            "design_review",
            "Validate the seven design documents and executable playtest contract.",
            [],
            ["all design v2 documents pass structural and genre validation"],
        ),
        _task(
            "module-selection",
            "module_reuse",
            "Resolve requested mechanics to reusable Unity modules before generating code.",
            ["design-review"],
            ["every known mechanic maps to exactly one selected reusable module"],
        ),
    ]
    code_task_ids: list[str] = []
    for module_id in design["unsupported_mechanics"]:
        task_id = f"generate-{module_id.replace('_', '-')}"
        code_task_ids.append(task_id)
        tasks.append(
            _task(
                task_id,
                "code_generation",
                f"Generate and statically validate the missing Unity module {module_id}.",
                ["module-selection"],
                [
                    f"{module_id} compiles against the repository-owned Unity API contract",
                    "the generated module binds to a scene object and exposes observable behavior",
                ],
                max_attempts=2,
            )
        )

    module_task_ids: list[str] = []
    for module_id in design["selected_modules"]:
        task_id = f"bind-module-{module_id.replace('_', '-')}"
        module_task_ids.append(task_id)
        tasks.append(
            _task(
                task_id,
                "module_reuse",
                f"Bind and configure reusable Unity module {module_id}.",
                ["module-selection"],
                [f"{module_id} is present, initialized, and connected to its owner"],
            )
        )

    tasks.append(
        _task(
            "configure-content",
            "content_configuration",
            "Validate content archetypes, quantities, behavior parameters, and placements.",
            ["design-review"],
            ["content definition counts match level placements"],
        )
    )
    zone_task_ids: list[str] = []
    for zone in design["design_v2"]["level_plan"]["zones"]:
        task_id = f"assemble-zone-{zone['zone_id'].replace('_', '-')}"
        zone_task_ids.append(task_id)
        tasks.append(
            _task(
                task_id,
                "level_assembly",
                f"Assemble and validate zone {zone['zone_id']}: {zone['challenge']}",
                ["configure-content"],
                [
                    "platform route is traversable under movement constraints",
                    "planned enemies, hazards, rewards, and checkpoint are placed",
                ],
            )
        )
    tasks.append(
        _task(
            "bind-presentation",
            "ui_binding",
            "Bind HUD, state transitions, camera feedback, and presentation cues.",
            [*zone_task_ids] or ["configure-content"],
            ["required HUD and gameplay feedback controllers are initialized"],
        )
    )

    assembly_dependencies = [
        "module-selection",
        *module_task_ids,
        *code_task_ids,
        "bind-presentation",
    ]
    tasks.extend(
        [
            _task(
                "unity-project-generation",
                "project_generation",
                "Generate the Unity project, scripts, design files, scene request, and asset requests.",
                assembly_dependencies,
                ["the generated project is complete and has a resolvable Bootstrap scene"],
            ),
            _task(
                "unity-playmode-validation",
                "unity_validation",
                "Compile the project and execute the validation_plan Play Mode scenarios.",
                ["unity-project-generation"],
                [
                    "Unity batch compilation and scene assembly pass",
                    "all executable validation scenarios pass in Play Mode",
                ],
            ),
            _task(
                "quality-evaluation",
                "quality_evaluation",
                "Score playtest completion, feature use, structure, content, and feedback.",
                ["unity-playmode-validation"],
                ["objective game quality score meets the configured threshold"],
            ),
            _task(
                "package-project",
                "packaging",
                "Package the validated Unity project and preserve development evidence.",
                ["quality-evaluation"],
                ["a deterministic Unity project archive and task report are available"],
            ),
        ]
    )
    return {
        "plan_version": "1.0.0",
        "genre": design["game_spec"]["genre"],
        "time_budget_seconds": time_budget_seconds,
        "tasks": tasks,
    }


def _task(
    task_id: str,
    category: Literal[
        "design_review",
        "module_reuse",
        "code_generation",
        "content_configuration",
        "level_assembly",
        "ui_binding",
        "project_generation",
        "unity_validation",
        "quality_evaluation",
        "packaging",
    ],
    description: str,
    dependencies: list[str],
    acceptance_criteria: list[str],
    *,
    max_attempts: int = 1,
) -> ImplementationTask:
    return {
        "task_id": task_id,
        "category": category,
        "description": description,
        "dependencies": dependencies,
        "acceptance_criteria": acceptance_criteria,
        "max_attempts": max_attempts,
        "attempts": 0,
        "status": "pending",
        "evidence": [],
        "last_error": None,
    }

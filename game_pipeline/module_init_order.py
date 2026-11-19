"""Keep Unity module initialization behind the services required at startup."""

from __future__ import annotations

from collections.abc import Iterable

# These dependencies come from GetRequired<T>() calls in the reusable modules'
# OnInitialize methods. GameBootstrap initializes modules in selectedModules order.
MODULE_INIT_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "save_system": ("game_state_store",),
    "platformer_movement": ("input_adapter",),
    "wall_climb": ("input_adapter",),
    "air_dash": ("input_adapter",),
    "top_down_movement": ("input_adapter",),
    "card_effect_system": ("card_resource_system", "deck_system"),
    "activity_system": ("stat_system", "time_turn_system"),
    "schedule_system": ("time_turn_system",),
    "raising_ending_resolver": ("stat_system",),
    "choice_branch_system": ("flag_system",),
    "ending_resolver": ("flag_system",),
    "auto_target_system": ("projectile_system",),
    "tower_targeting_system": ("projectile_system",),
    "upgrade_selection_system": ("experience_system", "rarity_system"),
}


def order_selected_modules(module_ids: Iterable[str]) -> list[str]:
    """Add known prerequisites and preserve the original order where possible."""

    ordered: list[str] = []
    state: dict[str, int] = {}

    def visit(module_id: str) -> None:
        if state.get(module_id) == 2:
            return
        if state.get(module_id) == 1:
            raise ValueError(f"Unity module initialization dependency cycle: {module_id}")
        state[module_id] = 1
        for prerequisite in MODULE_INIT_DEPENDENCIES.get(module_id, ()):
            visit(prerequisite)
        state[module_id] = 2
        ordered.append(module_id)

    for module_id in module_ids:
        visit(module_id)
    return ordered


def module_dependency_issues(module_ids: Iterable[str]) -> list[str]:
    """Explain missing or late prerequisites in a serialized Unity module list."""

    positions = {module_id: index for index, module_id in enumerate(module_ids)}
    issues: list[str] = []
    for module_id, index in positions.items():
        for prerequisite in MODULE_INIT_DEPENDENCIES.get(module_id, ()):
            prerequisite_index = positions.get(prerequisite)
            if prerequisite_index is None:
                issues.append(f"{module_id} requires missing {prerequisite}")
            elif prerequisite_index > index:
                issues.append(f"{module_id} must initialize after {prerequisite}")
    return issues

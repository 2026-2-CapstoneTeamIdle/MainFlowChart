"""Genre-level playability rules that every generated implementation must preserve."""

from __future__ import annotations

from mainflow.contracts import GenreProfile

COMMON_RUNTIME_INVARIANTS = (
    "The player starts in an active controllable state; no win, loss, pause, or game-over state "
    "may be active on the first playable frame.",
    "Every resource required to stay alive or take the first action has a valid positive initial "
    "value and is initialized before systems read it.",
    "The spawn area is safe long enough to understand the controls and cannot overlap an "
    "immediate lethal hazard or hostile contact.",
    "The core interaction changes observable world state and the HUD reports the same state.",
    "A complete core-loop cycle can be played from start through challenge, reward, progression, "
    "and a reachable win or loss outcome.",
)

GENRE_RUNTIME_INVARIANTS: dict[GenreProfile, tuple[str, ...]] = {
    "Platformer": (
        "Player health, movement speed, jump capability, spawn support, camera tracking, and a "
        "reachable goal are valid before control begins.",
        "Required collectibles and goal objects exist in the scene and their authored totals "
        "match the HUD totals.",
    ),
    "TowerDefense": (
        "Starting currency can purchase at least one legal tower and build controls and costs are "
        "visible before the first wave becomes dangerous.",
        "Enemies follow a complete path, towers can damage them, kills grant currency, and leaked "
        "enemies damage a positive starting base life total.",
    ),
    "CardGame": (
        "The opening hand, draw pile, positive player health, turn owner, and enough starting "
        "resources for at least one legal action are initialized before input.",
        "At least one playable card can resolve its stated effect and advance the turn.",
    ),
    "VisualNovel": (
        "The first dialogue node and speaker are valid and at least one input can advance the "
        "conversation without entering an ending immediately.",
        "Every presented choice points to an existing branch and at least one ending is reachable.",
    ),
    "RaisingSimulation": (
        "Initial date, action points, character stats, fatigue, and currency are within their valid "
        "ranges and permit at least one activity.",
        "An activity changes time and stats, conditional events can trigger, and the schedule can "
        "reach an ending.",
    ),
    "SurvivorLike": (
        "Player current health equals a positive maximum health before enemy contact; the health "
        "system must not report game over at startup.",
        "Enemies spawn outside contact range, chase the player, deal bounded contact damage with "
        "a cooldown, and cannot drain full starting health in the first safe interval.",
        "The exact requested attack delivery damages enemies; do not replace orbiting, melee, "
        "beam, summon, or projectile behavior with another delivery method.",
        "Defeated enemies grant progression through the exact requested delivery path, including "
        "spawn and pickup when a dropped collectible is requested.",
        "Level-up presents the requested number of valid choices, selection changes the advertised "
        "stat, difficulty increases over time, and any promised boss is actually spawned.",
    ),
}

REQUIRED_CAUSAL_TRANSITIONS: dict[GenreProfile, tuple[str, ...]] = {
    "Platformer": (
        "platformer.collectible_to_progress",
        "platformer.hazard_to_health",
        "platformer.death_to_checkpoint",
        "platformer.requirements_to_clear",
    ),
    "TowerDefense": (
        "tower.build_to_currency",
        "tower.spawn_to_path",
        "tower.attack_to_damage",
        "tower.death_to_reward",
    ),
    "SurvivorLike": (
        "survivor.spawn_to_chase",
        "survivor.attack_to_damage",
        "survivor.death_to_progression",
        "survivor.xp_to_choices",
        "survivor.choice_to_stat",
    ),
    "CardGame": (),
    "VisualNovel": (),
    "RaisingSimulation": (),
}


def runtime_invariants_for_genre(genre: GenreProfile) -> list[str]:
    """Return common and genre-specific rules as an immutable prompt/validation contract."""

    return [*COMMON_RUNTIME_INVARIANTS, *GENRE_RUNTIME_INVARIANTS[genre]]

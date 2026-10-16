"""Game-design planning used by the game pipeline nodes."""

from game_pipeline.design_catalog import build_game_logic_design, normalize_game_spec
from game_pipeline.game_blueprint import build_game_blueprint
from game_pipeline.blueprint_planner import (
    GameBlueprintPlanner,
    create_blueprint_planner_from_environment,
)
from game_pipeline.feature_planner import FeatureMechanicPlan, plan_feature_mechanics
from game_pipeline.implementation_planner import build_implementation_plan
from game_pipeline.gemini_feature_generator import (
    GeminiApiClient,
    GeminiFeatureGenerator,
    LocalAIJsonClient,
    attach_generated_modules,
    create_feature_generator_from_environment,
)
from game_pipeline.unity_project_generator import UnityGenerationResult, UnityProjectGenerator
from game_pipeline.unity_asset_applicator import (
    UnityAssetApplicationResult,
    UnityAssetApplicator,
)
from game_pipeline.unity_project_validator import (
    UnityProjectValidator,
    UnityValidationOutcome,
)

__all__ = [
    "UnityAssetApplicationResult",
    "UnityAssetApplicator",
    "UnityGenerationResult",
    "UnityProjectGenerator",
    "UnityProjectValidator",
    "UnityValidationOutcome",
    "FeatureMechanicPlan",
    "GameBlueprintPlanner",
    "GeminiApiClient",
    "GeminiFeatureGenerator",
    "LocalAIJsonClient",
    "attach_generated_modules",
    "build_game_logic_design",
    "build_game_blueprint",
    "build_implementation_plan",
    "create_feature_generator_from_environment",
    "create_blueprint_planner_from_environment",
    "normalize_game_spec",
    "plan_feature_mechanics",
]

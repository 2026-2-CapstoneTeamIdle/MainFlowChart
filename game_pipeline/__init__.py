"""Game-design planning used by the game pipeline nodes."""

from game_pipeline.blueprint_planner import (
    GameBlueprintPlanner,
    create_blueprint_planner_from_environment,
)
from game_pipeline.claude_code import (
    ClaudeCodeGameHarness,
    ClaudeCodeHarnessSettings,
    run_claude_code_quality_review,
)
from game_pipeline.codex_cli import (
    CodexGameHarness,
    CodexHarnessSettings,
    run_codex_quality_review,
)
from game_pipeline.codex_cli.config import resolve_game_builder
from game_pipeline.codex_cli.harness import prepare_design_for_codex
from game_pipeline.design_catalog import build_game_logic_design, normalize_game_spec
from game_pipeline.design_v2 import build_design_v2, validate_design_v2
from game_pipeline.design_v2_planner import (
    StagedDesignV2Planner,
    create_design_v2_planner_from_environment,
)
from game_pipeline.feature_planner import FeatureMechanicPlan, plan_feature_mechanics
from game_pipeline.game_blueprint import build_game_blueprint
from game_pipeline.game_development_loop import GameDevelopmentLoop
from game_pipeline.game_quality_validator_ai import (
    GameQualityValidatorAI,
    GameValidatorAIReport,
    create_game_quality_validator_from_environment,
)
from game_pipeline.gemini_feature_generator import (
    GeminiApiClient,
    GeminiFeatureGenerator,
    LocalAIJsonClient,
    OpenAIJsonClient,
    attach_generated_modules,
    create_feature_generator_from_environment,
    resolve_feature_provider_from_environment,
)
from game_pipeline.genre_feature_enricher import (
    GenreFeatureEnricher,
    create_genre_feature_enricher_from_environment,
)
from game_pipeline.implementation_planner import build_implementation_plan
from game_pipeline.implementation_task_planner import build_implementation_tasks
from game_pipeline.project_context_index import (
    build_project_context_index,
    compact_api_contract,
    retrieve_prompt_api_contract,
)
from game_pipeline.project_context_reviewer import (
    ProjectContextReview,
    ProjectContextReviewer,
    create_project_context_reviewer_from_environment,
    review_feedback,
)
from game_pipeline.unity_asset_applicator import (
    UnityAssetApplicationResult,
    UnityAssetApplicator,
)
from game_pipeline.unity_project_generator import UnityGenerationResult, UnityProjectGenerator
from game_pipeline.unity_project_validator import (
    UnityProjectValidator,
    UnityValidationOutcome,
)

__all__ = [
    "ClaudeCodeGameHarness",
    "ClaudeCodeHarnessSettings",
    "CodexGameHarness",
    "CodexHarnessSettings",
    "FeatureMechanicPlan",
    "GameBlueprintPlanner",
    "GameDevelopmentLoop",
    "GameQualityValidatorAI",
    "GameValidatorAIReport",
    "GeminiApiClient",
    "GeminiFeatureGenerator",
    "GenreFeatureEnricher",
    "LocalAIJsonClient",
    "OpenAIJsonClient",
    "ProjectContextReview",
    "ProjectContextReviewer",
    "StagedDesignV2Planner",
    "UnityAssetApplicationResult",
    "UnityAssetApplicator",
    "UnityGenerationResult",
    "UnityProjectGenerator",
    "UnityProjectValidator",
    "UnityValidationOutcome",
    "attach_generated_modules",
    "build_design_v2",
    "build_game_blueprint",
    "build_game_logic_design",
    "build_implementation_plan",
    "build_implementation_tasks",
    "build_project_context_index",
    "compact_api_contract",
    "create_blueprint_planner_from_environment",
    "create_design_v2_planner_from_environment",
    "create_feature_generator_from_environment",
    "create_game_quality_validator_from_environment",
    "create_genre_feature_enricher_from_environment",
    "create_project_context_reviewer_from_environment",
    "normalize_game_spec",
    "plan_feature_mechanics",
    "prepare_design_for_codex",
    "resolve_feature_provider_from_environment",
    "resolve_game_builder",
    "retrieve_prompt_api_contract",
    "review_feedback",
    "run_claude_code_quality_review",
    "run_codex_quality_review",
    "validate_design_v2",
]

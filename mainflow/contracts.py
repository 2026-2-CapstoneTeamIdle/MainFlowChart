"""Shared data contracts for every agent in the game-generation workflow.

This module is the machine-readable source of truth.  Human-readable rules and
the agent input/output matrix live in ``docs/ContractRule.md``.
"""

from __future__ import annotations

from typing import Literal, NotRequired, TypedDict

ContractVersion = Literal["3.3.0"]
CONTRACT_VERSION: ContractVersion = "3.3.0"

ImageStyle = Literal["Pixel Art", "Anime", "Cartoon", "Realistic", "Low Poly", "Custom"]
MoodStyle = Literal["Cyberpunk", "Medieval", "Modern", "Fantasy", "Horror", "Cozy"]
Viewpoint = Literal["사이드뷰", "탑다운", "쿼터뷰", "고정 화면"]
GameGenre = Literal[
    "플랫포머",
    "타워 디펜스",
    "카드",
    "비주얼 노벨",
    "육성 시뮬레이션",
    "뱀서류",
]
GenreProfile = Literal[
    "Platformer",
    "TowerDefense",
    "CardGame",
    "SurvivorLike",
    "VisualNovel",
    "RaisingSimulation",
]
AssetType = Literal["image", "sound"]
ImageAssetKind = Literal["sprite", "portrait", "ui", "tileset", "illustration", "background"]
SoundAssetKind = Literal["bgm", "sfx", "ui", "voice", "ambience"]
UnitySpriteMode = Literal["single", "multiple"]
UnityAudioLoadType = Literal["decompress_on_load", "compressed_in_memory", "streaming"]
AudioChannelMode = Literal["mono", "stereo"]
DraftStatus = Literal["pending", "generated", "failed"]
ValidationStatus = Literal["pending", "passed", "failed", "needs_revision"]
Severity = Literal["info", "warning", "error"]
ValidationTarget = Literal["game", "image", "sound", "integration"]
IntegrationStatus = Literal["pending", "integrated", "failed"]
ArtifactCategory = Literal["image", "sound", "game", "data", "validation"]


class ArtifactReference(TypedDict):
    contract_version: ContractVersion
    artifact_id: str
    project_id: str
    category: ArtifactCategory
    relative_path: str
    media_type: str
    size_bytes: int
    sha256: str
    created_at: str
    producer: str


# ---------------------------------------------------------------------------
# Domain payloads shared between agents
# ---------------------------------------------------------------------------
class GameFeature(TypedDict):
    feature_id: str
    description: str
    required: bool


class AssetRequirement(TypedDict):
    asset_id: str
    asset_type: AssetType
    purpose: str
    description: str
    required: bool


class ImageGenerationSpec(TypedDict):
    kind: ImageAssetKind
    width: int
    height: int
    transparent: bool
    sprite_mode: UnitySpriteMode
    pixels_per_unit: int
    tile_width: NotRequired[int]
    tile_height: NotRequired[int]
    columns: NotRequired[int]
    rows: NotRequired[int]


class SoundGenerationSpec(TypedDict):
    kind: SoundAssetKind
    target_duration_seconds: float
    loop: bool
    channels: AudioChannelMode
    sample_rate_hz: int
    unity_load_type: UnityAudioLoadType
    mixer_group: str
    spatial_blend: float


class AssetGenerationItem(AssetRequirement):
    suggested_filename: str
    unity_binding_key: str
    generation_spec: ImageGenerationSpec | SoundGenerationSpec


class AssetGenerationRequest(TypedDict):
    contract_version: ContractVersion
    request_id: str
    source_design_id: str
    game_title: str
    genre: GenreProfile
    asset_type: AssetType
    image_style: ImageStyle
    mood_style: MoodStyle
    viewpoint: Viewpoint
    reference_image: ArtifactReference | None
    output_directory: str
    assets: list[AssetGenerationItem]


class GameSpec(TypedDict):
    title: str
    genre: GenreProfile
    viewpoint: Viewpoint
    features: list[GameFeature]
    mechanics: list[str]
    controls: dict[str, str]
    win_conditions: list[str]
    lose_conditions: list[str]
    target_engine: Literal["Unity"]
    asset_requirements: list[AssetRequirement]


class GeneratedGameModule(TypedDict):
    module_id: str
    feature_id: str
    feature_description: str
    class_name: str
    source_code: str
    source_sha256: str


class ImplementationSystem(TypedDict):
    system_id: str
    module_ids: list[str]
    depends_on: list[str]
    responsibilities: list[str]


class PlannedContent(TypedDict):
    archetype: str
    count: int
    purpose: str


class PlaytestScenario(TypedDict):
    scenario_id: str
    title: str
    steps: list[str]
    assertions: list[str]


class GameImplementationPlan(TypedDict):
    plan_version: Literal["1.0.0"]
    complexity_tier: Literal["advanced_prototype"]
    minimum_session_minutes: int
    core_loop_phases: list[str]
    systems: list[ImplementationSystem]
    content: list[PlannedContent]
    ui_screens: list[str]
    playtest_scenarios: list[PlaytestScenario]


class BlueprintContentDirective(TypedDict):
    archetype: str
    count: int
    purpose: str


class BlueprintEntity(TypedDict):
    entity_id: str
    display_name: str
    archetype: str
    position_x: float
    position_y: float
    scale_x: float
    scale_y: float
    color_hex: str
    behavior_tags: list[str]


class BlueprintProgressionOption(TypedDict):
    option_id: str
    display_name: str
    description: str
    rarity: Literal["common", "rare", "epic", "legendary"]


class GameBlueprint(TypedDict):
    blueprint_version: Literal["1.0.0"]
    blueprint_id: str
    source: Literal["deterministic", "local", "gemini"]
    title: str
    summary: str
    scene_width: float
    scene_height: float
    background_color_hex: str
    core_loop: list[str]
    content: list[BlueprintContentDirective]
    entities: list[BlueprintEntity]
    progression_options: list[BlueprintProgressionOption]
    ui_labels: list[str]


class GameLogicDesign(TypedDict):
    contract_version: ContractVersion
    design_id: str
    game_spec: GameSpec
    common_modules: list[str]
    genre_modules: list[str]
    selected_modules: list[str]
    unsupported_mechanics: list[str]
    generated_modules: list[GeneratedGameModule]
    implementation_plan: GameImplementationPlan
    game_blueprint: GameBlueprint


class ParsedRequest(TypedDict):
    contract_version: ContractVersion
    image_style: ImageStyle
    mood_style: MoodStyle
    genre: GameGenre
    viewpoint: Viewpoint
    condition: str
    custom_image: ArtifactReference | None


class FeatureRequirement(TypedDict):
    feature_id: str
    name: str
    description: str
    source_text: str


class AnalysisResult(TypedDict):
    contract_version: ContractVersion
    analysis_id: str
    condition_summary: str
    features: list[FeatureRequirement]


class LogicAnalysis(TypedDict):
    contract_version: ContractVersion
    logic_analysis_id: str
    genre: GameGenre
    viewpoint: Viewpoint
    mood_style: MoodStyle
    core_loop: str
    features: list[FeatureRequirement]
    criteria: list[ValidationCriterion]


class ValidationCriterion(TypedDict):
    criterion_id: str
    target: ValidationTarget
    description: str
    required: bool


class ValidationCheckResult(TypedDict):
    criterion_id: str
    passed: bool
    message: str


class ValidationIssueRequired(TypedDict):
    code: str
    severity: Severity
    message: str


class ValidationIssue(ValidationIssueRequired, total=False):
    target_id: str


class ImageAsset(TypedDict):
    asset_id: str
    name: str
    kind: ImageAssetKind
    unity_binding_key: str
    artifact: ArtifactReference
    file_format: str
    width: int
    height: int
    prompt: str


class ImageDraft(TypedDict):
    contract_version: ContractVersion
    draft_id: str
    status: DraftStatus
    assets: list[ImageAsset]
    missing_required_asset_ids: list[str]
    notes: list[str]


class SoundAssetRequired(TypedDict):
    asset_id: str
    name: str
    kind: SoundAssetKind
    unity_binding_key: str
    artifact: ArtifactReference
    file_format: str
    duration_seconds: float
    loop: bool
    mixer_group: str
    prompt: str


class SoundAsset(SoundAssetRequired, total=False):
    provider: str  # "procedural" marks a fallback placeholder that needs human review


class SoundDraft(TypedDict):
    contract_version: ContractVersion
    draft_id: str
    status: DraftStatus
    assets: list[SoundAsset]
    missing_required_asset_ids: list[str]
    notes: list[str]


class GameLogicDraft(TypedDict):
    contract_version: ContractVersion
    draft_id: str
    status: DraftStatus
    engine: str
    entry_scene: str | None
    source_artifacts: list[ArtifactReference]
    required_image_asset_ids: list[str]
    required_sound_asset_ids: list[str]
    notes: list[str]


class GameValidationResult(TypedDict):
    contract_version: ContractVersion
    status: ValidationStatus
    checks: list[ValidationCheckResult]
    issues: list[ValidationIssue]


class AssetValidationSpec(TypedDict):
    contract_version: ContractVersion
    spec_id: str
    image_criteria: list[ValidationCriterion]
    sound_criteria: list[ValidationCriterion]


class ImageValidationResult(TypedDict):
    contract_version: ContractVersion
    status: ValidationStatus
    checks: list[ValidationCheckResult]
    issues: list[ValidationIssue]
    validated_asset_ids: list[str]


class SoundValidationResult(TypedDict):
    contract_version: ContractVersion
    status: ValidationStatus
    checks: list[ValidationCheckResult]
    issues: list[ValidationIssue]
    validated_asset_ids: list[str]


class AssetBindingEntry(TypedDict):
    asset_id: str
    asset_type: AssetType
    kind: str
    unity_binding_key: str
    unity_path: str
    required: bool
    sprite_mode: str
    pixels_per_unit: int
    transparent: bool
    tile_width: int
    tile_height: int
    columns: int
    rows: int
    loop: bool
    unity_load_type: str
    mixer_group: str
    spatial_blend: float


class AssetBindingManifest(TypedDict):
    binding_version: Literal["1.0.0"]
    contract_version: ContractVersion
    image_style: ImageStyle
    entries: list[AssetBindingEntry]
    missing_required_asset_ids: list[str]
    warnings: list[str]


class IntegratedGame(TypedDict):
    contract_version: ContractVersion
    status: IntegrationStatus
    entry_artifact: ArtifactReference | None
    game_artifacts: list[ArtifactReference]
    applied_image_asset_ids: list[str]
    applied_sound_asset_ids: list[str]
    notes: list[str]


class FinalValidationResult(TypedDict):
    contract_version: ContractVersion
    status: ValidationStatus
    checks: list[ValidationCheckResult]
    issues: list[ValidationIssue]


# ---------------------------------------------------------------------------
# LangGraph shared state
# total=False is intentional because the graph fills fields incrementally.
# ---------------------------------------------------------------------------
class WorkflowState(TypedDict, total=False):
    image_style: ImageStyle
    mood_style: MoodStyle
    genre: GameGenre
    viewpoint: Viewpoint
    condition: str
    custom_image_path: str
    project_id: str
    parsed_request: ArtifactReference
    analysis: ArtifactReference
    logic_analysis: ArtifactReference
    image_asset_request: ArtifactReference
    sound_asset_request: ArtifactReference
    image_draft: ArtifactReference
    game_logic_draft: ArtifactReference
    sound_draft: ArtifactReference
    game_validation_result: ArtifactReference
    asset_validation_spec: ArtifactReference
    image_validation_result: ArtifactReference
    sound_validation_result: ArtifactReference
    integrated_game: ArtifactReference
    final_validation_result: ArtifactReference


# ---------------------------------------------------------------------------
# Agent boundary contracts
# An agent receives the declared input view of WorkflowState and returns only
# the declared patch.  Extra state keys may exist at runtime and are ignored.
# ---------------------------------------------------------------------------
class UserInputAgentInput(TypedDict, total=False):
    image_style: ImageStyle
    mood_style: MoodStyle
    genre: GameGenre
    viewpoint: Viewpoint
    condition: str
    custom_image_path: str


class UserInputAgentOutput(TypedDict):
    image_style: ImageStyle
    mood_style: MoodStyle
    genre: GameGenre
    viewpoint: Viewpoint
    condition: str
    custom_image_path: NotRequired[str]


class ParseInputAgentInput(TypedDict):
    image_style: ImageStyle
    mood_style: MoodStyle
    genre: GameGenre
    viewpoint: Viewpoint
    condition: str
    custom_image_path: NotRequired[str]


class ParseInputAgentOutput(TypedDict):
    project_id: str
    parsed_request: ArtifactReference


class AnalysisAgentInput(TypedDict):
    project_id: str
    parsed_request: ArtifactReference


class AnalysisAgentOutput(TypedDict):
    analysis: ArtifactReference


class LogicAnalysisAgentInput(TypedDict):
    project_id: str
    parsed_request: ArtifactReference
    analysis: ArtifactReference


class LogicAnalysisAgentOutput(TypedDict):
    logic_analysis: ArtifactReference


class GenerateImageAgentInput(TypedDict):
    project_id: str
    parsed_request: ArtifactReference
    analysis: ArtifactReference
    logic_analysis: ArtifactReference
    image_asset_request: ArtifactReference


class GenerateImageAgentOutput(TypedDict):
    image_draft: ArtifactReference


class DesignGameLogicAgentInput(TypedDict):
    project_id: str
    parsed_request: ArtifactReference
    analysis: ArtifactReference
    logic_analysis: ArtifactReference


class DesignGameLogicAgentOutput(TypedDict):
    game_logic_draft: ArtifactReference
    image_asset_request: ArtifactReference
    sound_asset_request: ArtifactReference


class GenerateSoundAgentInput(TypedDict):
    project_id: str
    parsed_request: ArtifactReference
    analysis: ArtifactReference
    logic_analysis: ArtifactReference
    sound_asset_request: ArtifactReference


class GenerateSoundAgentOutput(TypedDict):
    sound_draft: ArtifactReference


class ValidateGameAgentInput(TypedDict):
    project_id: str
    parsed_request: ArtifactReference
    logic_analysis: ArtifactReference
    game_logic_draft: ArtifactReference


class ValidateGameAgentOutput(TypedDict):
    game_validation_result: ArtifactReference


class AssetValidationSpecAgentInput(TypedDict):
    project_id: str
    parsed_request: ArtifactReference
    game_validation_result: ArtifactReference


class AssetValidationSpecAgentOutput(TypedDict):
    asset_validation_spec: ArtifactReference


class ValidateImageAgentInput(TypedDict):
    project_id: str
    parsed_request: ArtifactReference
    image_asset_request: ArtifactReference
    image_draft: ArtifactReference
    asset_validation_spec: ArtifactReference


class ValidateImageAgentOutput(TypedDict):
    image_validation_result: ArtifactReference


class ValidateSoundAgentInput(TypedDict):
    project_id: str
    parsed_request: ArtifactReference
    sound_asset_request: ArtifactReference
    sound_draft: ArtifactReference
    asset_validation_spec: ArtifactReference


class ValidateSoundAgentOutput(TypedDict):
    sound_validation_result: ArtifactReference


class ApplyAssetsAgentInput(TypedDict):
    project_id: str
    game_logic_draft: ArtifactReference
    image_asset_request: ArtifactReference
    sound_asset_request: ArtifactReference
    image_draft: ArtifactReference
    sound_draft: ArtifactReference
    image_validation_result: ArtifactReference
    sound_validation_result: ArtifactReference


class ApplyAssetsAgentOutput(TypedDict):
    integrated_game: ArtifactReference


class FinalValidationAgentInput(TypedDict):
    project_id: str
    logic_analysis: ArtifactReference
    integrated_game: ArtifactReference


class FinalValidationAgentOutput(TypedDict):
    final_validation_result: ArtifactReference

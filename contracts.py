"""Shared data contracts for every agent in the game-generation workflow.

This module is the machine-readable source of truth.  Human-readable rules and
the agent input/output matrix live in ``ContractRule.md``.
"""

from __future__ import annotations

from typing import Literal, TypedDict


ContractVersion = Literal["2.0.0"]
CONTRACT_VERSION: ContractVersion = "2.0.0"

ImageStyle = Literal["Pixel Art", "Anime", "Cartoon", "Realistic", "Low Poly"]
GameGenre = Literal["Action", "RPG", "Platformer", "Puzzle", "Simulation"]
QualityLevel = Literal["Low", "Medium", "High"]
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
class ParsedRequest(TypedDict):
    contract_version: ContractVersion
    image_style: ImageStyle
    genre: GameGenre
    quality: QualityLevel


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


class InitialFinalValidationSpec(TypedDict):
    contract_version: ContractVersion
    spec_id: str
    criteria: list[ValidationCriterion]


class ImageAsset(TypedDict):
    asset_id: str
    name: str
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
    notes: list[str]


class SoundAsset(TypedDict):
    asset_id: str
    name: str
    artifact: ArtifactReference
    file_format: str
    duration_seconds: float
    prompt: str


class SoundDraft(TypedDict):
    contract_version: ContractVersion
    draft_id: str
    status: DraftStatus
    assets: list[SoundAsset]
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
    genre: GameGenre
    quality: QualityLevel
    project_id: str
    parsed_request: ArtifactReference
    initial_final_validation_spec: ArtifactReference
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
    genre: GameGenre
    quality: QualityLevel


class UserInputAgentOutput(TypedDict):
    image_style: ImageStyle
    genre: GameGenre
    quality: QualityLevel


class ParseInputAgentInput(TypedDict):
    image_style: ImageStyle
    genre: GameGenre
    quality: QualityLevel


class ParseInputAgentOutput(TypedDict):
    project_id: str
    parsed_request: ArtifactReference


class InitialValidationSpecAgentInput(TypedDict):
    project_id: str
    parsed_request: ArtifactReference


class InitialValidationSpecAgentOutput(TypedDict):
    initial_final_validation_spec: ArtifactReference


class GenerateImageAgentInput(TypedDict):
    project_id: str
    parsed_request: ArtifactReference
    initial_final_validation_spec: ArtifactReference


class GenerateImageAgentOutput(TypedDict):
    image_draft: ArtifactReference


class DesignGameLogicAgentInput(TypedDict):
    project_id: str
    parsed_request: ArtifactReference
    initial_final_validation_spec: ArtifactReference


class DesignGameLogicAgentOutput(TypedDict):
    game_logic_draft: ArtifactReference


class GenerateSoundAgentInput(TypedDict):
    project_id: str
    parsed_request: ArtifactReference
    initial_final_validation_spec: ArtifactReference


class GenerateSoundAgentOutput(TypedDict):
    sound_draft: ArtifactReference


class ValidateGameAgentInput(TypedDict):
    project_id: str
    parsed_request: ArtifactReference
    initial_final_validation_spec: ArtifactReference
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
    image_draft: ArtifactReference
    asset_validation_spec: ArtifactReference


class ValidateImageAgentOutput(TypedDict):
    image_validation_result: ArtifactReference


class ValidateSoundAgentInput(TypedDict):
    project_id: str
    parsed_request: ArtifactReference
    sound_draft: ArtifactReference
    asset_validation_spec: ArtifactReference


class ValidateSoundAgentOutput(TypedDict):
    sound_validation_result: ArtifactReference


class ApplyAssetsAgentInput(TypedDict):
    project_id: str
    game_logic_draft: ArtifactReference
    image_draft: ArtifactReference
    sound_draft: ArtifactReference
    image_validation_result: ArtifactReference
    sound_validation_result: ArtifactReference


class ApplyAssetsAgentOutput(TypedDict):
    integrated_game: ArtifactReference


class FinalValidationAgentInput(TypedDict):
    project_id: str
    initial_final_validation_spec: ArtifactReference
    integrated_game: ArtifactReference


class FinalValidationAgentOutput(TypedDict):
    final_validation_result: ArtifactReference

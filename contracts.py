"""Shared data contracts for every agent in the game-generation workflow.

This module is the machine-readable source of truth.  Human-readable rules and
the agent input/output matrix live in ``ContractRule.md``.
"""

from __future__ import annotations

from typing import Literal, TypedDict


ContractVersion = Literal["1.0.0"]
CONTRACT_VERSION: ContractVersion = "1.0.0"

ImageStyle = Literal["Pixel Art", "Anime", "Cartoon", "Realistic", "Low Poly"]
GameGenre = Literal["Action", "RPG", "Platformer", "Puzzle", "Simulation"]
QualityLevel = Literal["Low", "Medium", "High"]
DraftStatus = Literal["pending", "generated", "failed"]
ValidationStatus = Literal["pending", "passed", "failed", "needs_revision"]
Severity = Literal["info", "warning", "error"]
ValidationTarget = Literal["game", "image", "sound", "integration"]
IntegrationStatus = Literal["pending", "integrated", "failed"]


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
    file_path: str | None
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
    file_path: str | None
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
    project_path: str | None
    entry_scene: str | None
    source_files: list[str]
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
    project_path: str | None
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
    parsed_request: ParsedRequest
    initial_final_validation_spec: InitialFinalValidationSpec
    image_draft: ImageDraft
    game_logic_draft: GameLogicDraft
    sound_draft: SoundDraft
    game_validation_result: GameValidationResult
    asset_validation_spec: AssetValidationSpec
    image_validation_result: ImageValidationResult
    sound_validation_result: SoundValidationResult
    integrated_game: IntegratedGame
    final_validation_result: FinalValidationResult


# ---------------------------------------------------------------------------
# Agent boundary contracts
# An agent receives the declared input view of WorkflowState and returns only
# the declared patch.  Extra state keys may exist at runtime and are ignored.
# ---------------------------------------------------------------------------
class UserInputAgentInput(TypedDict, total=False):
    pass


class UserInputAgentOutput(TypedDict):
    image_style: ImageStyle
    genre: GameGenre
    quality: QualityLevel


class ParseInputAgentInput(TypedDict):
    image_style: ImageStyle
    genre: GameGenre
    quality: QualityLevel


class ParseInputAgentOutput(TypedDict):
    parsed_request: ParsedRequest


class InitialValidationSpecAgentInput(TypedDict):
    parsed_request: ParsedRequest


class InitialValidationSpecAgentOutput(TypedDict):
    initial_final_validation_spec: InitialFinalValidationSpec


class GenerateImageAgentInput(TypedDict):
    parsed_request: ParsedRequest
    initial_final_validation_spec: InitialFinalValidationSpec


class GenerateImageAgentOutput(TypedDict):
    image_draft: ImageDraft


class DesignGameLogicAgentInput(TypedDict):
    parsed_request: ParsedRequest
    initial_final_validation_spec: InitialFinalValidationSpec


class DesignGameLogicAgentOutput(TypedDict):
    game_logic_draft: GameLogicDraft


class GenerateSoundAgentInput(TypedDict):
    parsed_request: ParsedRequest
    initial_final_validation_spec: InitialFinalValidationSpec


class GenerateSoundAgentOutput(TypedDict):
    sound_draft: SoundDraft


class ValidateGameAgentInput(TypedDict):
    parsed_request: ParsedRequest
    initial_final_validation_spec: InitialFinalValidationSpec
    game_logic_draft: GameLogicDraft


class ValidateGameAgentOutput(TypedDict):
    game_validation_result: GameValidationResult


class AssetValidationSpecAgentInput(TypedDict):
    parsed_request: ParsedRequest
    game_validation_result: GameValidationResult


class AssetValidationSpecAgentOutput(TypedDict):
    asset_validation_spec: AssetValidationSpec


class ValidateImageAgentInput(TypedDict):
    parsed_request: ParsedRequest
    image_draft: ImageDraft
    asset_validation_spec: AssetValidationSpec


class ValidateImageAgentOutput(TypedDict):
    image_validation_result: ImageValidationResult


class ValidateSoundAgentInput(TypedDict):
    parsed_request: ParsedRequest
    sound_draft: SoundDraft
    asset_validation_spec: AssetValidationSpec


class ValidateSoundAgentOutput(TypedDict):
    sound_validation_result: SoundValidationResult


class ApplyAssetsAgentInput(TypedDict):
    game_logic_draft: GameLogicDraft
    image_draft: ImageDraft
    sound_draft: SoundDraft
    image_validation_result: ImageValidationResult
    sound_validation_result: SoundValidationResult


class ApplyAssetsAgentOutput(TypedDict):
    integrated_game: IntegratedGame


class FinalValidationAgentInput(TypedDict):
    initial_final_validation_spec: InitialFinalValidationSpec
    integrated_game: IntegratedGame


class FinalValidationAgentOutput(TypedDict):
    final_validation_result: FinalValidationResult

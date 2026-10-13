"""Deterministic mock Agents that use the production contracts and file system."""

from __future__ import annotations

import io
import math
import struct
import time
import wave
from dataclasses import dataclass
from datetime import date
from html import escape
from typing import Mapping, cast
from xml.etree import ElementTree

from mainflow.ArtifactManager import ArtifactManager
from mainflow.contracts import (
    CONTRACT_VERSION,
    AnalysisAgentInput,
    AnalysisAgentOutput,
    AnalysisResult,
    ApplyAssetsAgentInput,
    ApplyAssetsAgentOutput,
    AssetGenerationRequest,
    AssetValidationSpec,
    AssetValidationSpecAgentInput,
    AssetValidationSpecAgentOutput,
    DesignGameLogicAgentInput,
    DesignGameLogicAgentOutput,
    FinalValidationAgentInput,
    FinalValidationAgentOutput,
    FinalValidationResult,
    GameLogicDraft,
    GameValidationResult,
    GenerateImageAgentInput,
    GenerateImageAgentOutput,
    GenerateSoundAgentInput,
    GenerateSoundAgentOutput,
    ImageDraft,
    ImageValidationResult,
    IntegratedGame,
    LogicAnalysis,
    LogicAnalysisAgentInput,
    LogicAnalysisAgentOutput,
    ParsedRequest,
    ParseInputAgentInput,
    ParseInputAgentOutput,
    SoundDraft,
    SoundValidationResult,
    UserInputAgentInput,
    UserInputAgentOutput,
    ValidateGameAgentInput,
    ValidateGameAgentOutput,
    ValidateImageAgentInput,
    ValidateImageAgentOutput,
    ValidateSoundAgentInput,
    ValidateSoundAgentOutput,
)


@dataclass(frozen=True)
class MockRuntime:
    manager: ArtifactManager
    request: UserInputAgentOutput
    delays_ms: Mapping[str, float]
    project_date: date = date(2026, 9, 26)

    def delay(self, node_name: str) -> None:
        time.sleep(self.delays_ms.get(node_name, 0.0) / 1000.0)


def mock_user_input_node(
    state: UserInputAgentInput,
    runtime: MockRuntime,
) -> UserInputAgentOutput:
    runtime.delay("user_input")
    return dict(runtime.request)  # type: ignore[return-value]


def mock_parse_input_node(
    state: ParseInputAgentInput,
    runtime: MockRuntime,
) -> ParseInputAgentOutput:
    runtime.delay("parse_input")
    project_id = runtime.manager.create_project(runtime.project_date)
    payload: ParsedRequest = {
        "contract_version": CONTRACT_VERSION,
        "image_style": state["image_style"],
        "mood_style": state["mood_style"],
        "genre": state["genre"],
        "condition": state["condition"],
        "custom_image": None,
    }
    return {
        "project_id": project_id,
        "parsed_request": runtime.manager.write_json(
            project_id,
            "data",
            "parsed_request.json",
            payload,
            producer="parse_input",
        ),
    }


def mock_analysis_node(
    state: AnalysisAgentInput,
    runtime: MockRuntime,
) -> AnalysisAgentOutput:
    runtime.delay("analysis")
    request = cast(ParsedRequest, runtime.manager.read_json(state["parsed_request"]))
    payload: AnalysisResult = {
        "contract_version": CONTRACT_VERSION,
        "analysis_id": "mock-request-analysis",
        "condition_summary": request["condition"],
        "features": [
            {
                "feature_id": "feature-01",
                "name": "공격",
                "description": "플레이어가 적을 공격할 수 있다.",
                "source_text": request["condition"],
            },
        ],
    }
    return {
        "analysis": runtime.manager.write_json(
            state["project_id"],
            "data",
            "analysis.json",
            payload,
            producer="analysis",
        )
    }


def mock_logic_analysis_node(
    state: LogicAnalysisAgentInput,
    runtime: MockRuntime,
) -> LogicAnalysisAgentOutput:
    runtime.delay("logic_analysis")
    request = cast(ParsedRequest, runtime.manager.read_json(state["parsed_request"]))
    analysis = cast(AnalysisResult, runtime.manager.read_json(state["analysis"]))
    payload: LogicAnalysis = {
        "contract_version": CONTRACT_VERSION,
        "logic_analysis_id": "mock-logic-analysis",
        "genre": request["genre"],
        "mood_style": request["mood_style"],
        "core_loop": "Mock core loop",
        "features": analysis["features"],
        "criteria": [
            {
                "criterion_id": "game-runs",
                "target": "game",
                "description": "Mock game entry function executes successfully",
                "required": True,
            },
            {
                "criterion_id": "image-valid",
                "target": "image",
                "description": "Generated image is valid SVG",
                "required": True,
            },
            {
                "criterion_id": "sound-valid",
                "target": "sound",
                "description": "Generated sound is valid WAV",
                "required": True,
            },
            {
                "criterion_id": "integration-complete",
                "target": "integration",
                "description": "Validated assets are referenced by the game package",
                "required": True,
            },
        ],
    }
    return {
        "logic_analysis": runtime.manager.write_json(
            state["project_id"],
            "data",
            "logic_analysis.json",
            payload,
            producer="logic_analysis",
        )
    }


def mock_generate_image_node(
    state: GenerateImageAgentInput,
    runtime: MockRuntime,
) -> GenerateImageAgentOutput:
    runtime.delay("generate_image")
    request = cast(ParsedRequest, runtime.manager.read_json(state["parsed_request"]))
    cast(AnalysisResult, runtime.manager.read_json(state["analysis"]))
    cast(LogicAnalysis, runtime.manager.read_json(state["logic_analysis"]))
    asset_request = cast(
        AssetGenerationRequest,
        runtime.manager.read_json(state["image_asset_request"]),
    )
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64">'
        '<rect width="64" height="64" fill="#20283d"/>'
        '<circle cx="32" cy="32" r="18" fill="#62d9ff"/>'
        f"<title>{escape(request['image_style'])} mock player</title>"
        "</svg>"
    )
    image_reference = runtime.manager.write_text(
        state["project_id"],
        "image",
        "player.svg",
        svg,
        producer="generate_image",
        media_type="image/svg+xml",
    )
    draft: ImageDraft = {
        "contract_version": CONTRACT_VERSION,
        "draft_id": "mock-image-draft",
        "status": "generated",
        "assets": [
            {
                "asset_id": asset_request["assets"][0]["asset_id"],
                "name": "Mock Player",
                "artifact": image_reference,
                "file_format": "svg",
                "width": 64,
                "height": 64,
                "prompt": f"{request['image_style']} player character",
            }
        ],
        "notes": [],
    }
    return {
        "image_draft": runtime.manager.write_json(
            state["project_id"],
            "image",
            "image_draft.json",
            draft,
            producer="generate_image",
        )
    }


def mock_design_game_logic_node(
    state: DesignGameLogicAgentInput,
    runtime: MockRuntime,
) -> DesignGameLogicAgentOutput:
    runtime.delay("design_game_logic")
    request = cast(ParsedRequest, runtime.manager.read_json(state["parsed_request"]))
    cast(AnalysisResult, runtime.manager.read_json(state["analysis"]))
    cast(LogicAnalysis, runtime.manager.read_json(state["logic_analysis"]))
    source = f"def run_game():\n    return {{'genre': {request['genre']!r}, 'running': True}}\n"
    source_reference = runtime.manager.write_text(
        state["project_id"],
        "game",
        "mock_game.py",
        source,
        producer="design_game_logic",
        media_type="text/x-python; charset=utf-8",
    )
    draft: GameLogicDraft = {
        "contract_version": CONTRACT_VERSION,
        "draft_id": "mock-game-logic-draft",
        "status": "generated",
        "engine": "PythonMock",
        "entry_scene": "mock_game.py",
        "source_artifacts": [source_reference],
        "required_image_asset_ids": ["player-image"],
        "required_sound_asset_ids": ["theme-sound"],
        "notes": [],
    }
    image_request: AssetGenerationRequest = {
        "contract_version": CONTRACT_VERSION,
        "request_id": "mock-image-assets",
        "source_design_id": "mock-design",
        "game_title": "Mock Game",
        "genre": "SurvivorLike",
        "asset_type": "image",
        "creative_style": request["image_style"],
        "mood_style": request["mood_style"],
        "output_directory": "generated/images",
        "assets": [
            {
                "asset_id": "player-image",
                "asset_type": "image",
                "purpose": "player",
                "description": "Mock player image",
                "required": True,
                "suggested_filename": "player-image.png",
                "unity_binding_key": "asset_registry:player-image",
            }
        ],
    }
    sound_request: AssetGenerationRequest = {
        "contract_version": CONTRACT_VERSION,
        "request_id": "mock-sound-assets",
        "source_design_id": "mock-design",
        "game_title": "Mock Game",
        "genre": "SurvivorLike",
        "asset_type": "sound",
        "creative_style": request["mood_style"],
        "mood_style": request["mood_style"],
        "output_directory": "generated/sounds",
        "assets": [
            {
                "asset_id": "theme-sound",
                "asset_type": "sound",
                "purpose": "bgm",
                "description": "Mock theme sound",
                "required": True,
                "suggested_filename": "theme-sound.wav",
                "unity_binding_key": "asset_registry:theme-sound",
            }
        ],
    }
    return {
        "game_logic_draft": runtime.manager.write_json(
            state["project_id"],
            "game",
            "game_logic_draft.json",
            draft,
            producer="design_game_logic",
        ),
        "image_asset_request": runtime.manager.write_json(
            state["project_id"],
            "game",
            "asset_requests/image_asset_request.json",
            image_request,
            producer="design_game_logic",
        ),
        "sound_asset_request": runtime.manager.write_json(
            state["project_id"],
            "game",
            "asset_requests/sound_asset_request.json",
            sound_request,
            producer="design_game_logic",
        ),
    }


def _make_tone_wav(duration_seconds: float = 0.1, sample_rate: int = 8000) -> bytes:
    frames = bytearray()
    for index in range(int(duration_seconds * sample_rate)):
        sample = int(5000 * math.sin(2 * math.pi * 440 * index / sample_rate))
        frames.extend(struct.pack("<h", sample))
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(bytes(frames))
    return buffer.getvalue()


def mock_generate_sound_node(
    state: GenerateSoundAgentInput,
    runtime: MockRuntime,
) -> GenerateSoundAgentOutput:
    runtime.delay("generate_sound")
    request = cast(ParsedRequest, runtime.manager.read_json(state["parsed_request"]))
    cast(AnalysisResult, runtime.manager.read_json(state["analysis"]))
    cast(LogicAnalysis, runtime.manager.read_json(state["logic_analysis"]))
    asset_request = cast(
        AssetGenerationRequest,
        runtime.manager.read_json(state["sound_asset_request"]),
    )
    sound_reference = runtime.manager.write_bytes(
        state["project_id"],
        "sound",
        "theme.wav",
        _make_tone_wav(),
        producer="generate_sound",
        media_type="audio/wav",
    )
    draft: SoundDraft = {
        "contract_version": CONTRACT_VERSION,
        "draft_id": "mock-sound-draft",
        "status": "generated",
        "assets": [
            {
                "asset_id": asset_request["assets"][0]["asset_id"],
                "name": "Mock Theme",
                "artifact": sound_reference,
                "file_format": "wav",
                "duration_seconds": 0.1,
                "prompt": f"Short theme for a {request['genre']} game",
            }
        ],
        "notes": [],
    }
    return {
        "sound_draft": runtime.manager.write_json(
            state["project_id"],
            "sound",
            "sound_draft.json",
            draft,
            producer="generate_sound",
        )
    }


def mock_validate_game_node(
    state: ValidateGameAgentInput,
    runtime: MockRuntime,
) -> ValidateGameAgentOutput:
    runtime.delay("validate_game")
    draft = cast(
        GameLogicDraft,
        runtime.manager.read_json(state["game_logic_draft"]),
    )
    source = runtime.manager.read_text(draft["source_artifacts"][0])
    namespace: dict[str, object] = {}
    try:
        exec(compile(source, "mock_game.py", "exec"), namespace)
        run_result = namespace["run_game"]()  # type: ignore[operator]
        passed = bool(run_result["running"])  # type: ignore[index]
        message = "Mock game executed successfully"
        issues = []
    except Exception as error:  # pragma: no cover - exercised on mock failure only
        passed = False
        message = "Mock game execution failed"
        issues = [
            {
                "code": "GAME_EXECUTION_FAILED",
                "severity": "error",
                "message": str(error),
            }
        ]
    result: GameValidationResult = {
        "contract_version": CONTRACT_VERSION,
        "status": "passed" if passed else "failed",
        "checks": [
            {
                "criterion_id": "game-runs",
                "passed": passed,
                "message": message,
            }
        ],
        "issues": issues,  # type: ignore[typeddict-item]
    }
    return {
        "game_validation_result": runtime.manager.write_json(
            state["project_id"],
            "validation",
            "game_validation_result.json",
            result,
            producer="validate_game",
        )
    }


def mock_asset_validation_spec_node(
    state: AssetValidationSpecAgentInput,
    runtime: MockRuntime,
) -> AssetValidationSpecAgentOutput:
    runtime.delay("create_asset_validation_spec")
    game_result = cast(
        GameValidationResult,
        runtime.manager.read_json(state["game_validation_result"]),
    )
    if game_result["status"] != "passed":
        raise ValueError("Asset validation criteria require a valid game draft")
    payload: AssetValidationSpec = {
        "contract_version": CONTRACT_VERSION,
        "spec_id": "mock-asset-validation",
        "image_criteria": [
            {
                "criterion_id": "image-valid",
                "target": "image",
                "description": "SVG is parseable and has positive dimensions",
                "required": True,
            }
        ],
        "sound_criteria": [
            {
                "criterion_id": "sound-valid",
                "target": "sound",
                "description": "WAV is readable and has positive duration",
                "required": True,
            }
        ],
    }
    return {
        "asset_validation_spec": runtime.manager.write_json(
            state["project_id"],
            "validation",
            "asset_validation_spec.json",
            payload,
            producer="create_asset_validation_spec",
        )
    }


def mock_validate_image_node(
    state: ValidateImageAgentInput,
    runtime: MockRuntime,
) -> ValidateImageAgentOutput:
    runtime.delay("validate_image")
    draft = cast(ImageDraft, runtime.manager.read_json(state["image_draft"]))
    spec = cast(
        AssetValidationSpec,
        runtime.manager.read_json(state["asset_validation_spec"]),
    )
    asset = draft["assets"][0]
    root = ElementTree.fromstring(runtime.manager.read_text(asset["artifact"]))
    passed = (
        root.tag.endswith("svg")
        and asset["width"] > 0
        and asset["height"] > 0
        and bool(spec["image_criteria"])
    )
    result: ImageValidationResult = {
        "contract_version": CONTRACT_VERSION,
        "status": "passed" if passed else "failed",
        "checks": [
            {
                "criterion_id": "image-valid",
                "passed": passed,
                "message": "SVG parsed and dimensions are positive",
            }
        ],
        "issues": [],
        "validated_asset_ids": [asset["asset_id"]] if passed else [],
    }
    return {
        "image_validation_result": runtime.manager.write_json(
            state["project_id"],
            "validation",
            "image_validation_result.json",
            result,
            producer="validate_image",
        )
    }


def mock_validate_sound_node(
    state: ValidateSoundAgentInput,
    runtime: MockRuntime,
) -> ValidateSoundAgentOutput:
    runtime.delay("validate_sound")
    draft = cast(SoundDraft, runtime.manager.read_json(state["sound_draft"]))
    spec = cast(
        AssetValidationSpec,
        runtime.manager.read_json(state["asset_validation_spec"]),
    )
    asset = draft["assets"][0]
    with wave.open(io.BytesIO(runtime.manager.read_bytes(asset["artifact"])), "rb") as wav:
        duration = wav.getnframes() / wav.getframerate()
    passed = duration > 0 and bool(spec["sound_criteria"])
    result: SoundValidationResult = {
        "contract_version": CONTRACT_VERSION,
        "status": "passed" if passed else "failed",
        "checks": [
            {
                "criterion_id": "sound-valid",
                "passed": passed,
                "message": f"WAV duration is {duration:.3f} seconds",
            }
        ],
        "issues": [],
        "validated_asset_ids": [asset["asset_id"]] if passed else [],
    }
    return {
        "sound_validation_result": runtime.manager.write_json(
            state["project_id"],
            "validation",
            "sound_validation_result.json",
            result,
            producer="validate_sound",
        )
    }


def mock_apply_assets_node(
    state: ApplyAssetsAgentInput,
    runtime: MockRuntime,
) -> ApplyAssetsAgentOutput:
    runtime.delay("apply_assets_to_game")
    game = cast(GameLogicDraft, runtime.manager.read_json(state["game_logic_draft"]))
    images = cast(ImageDraft, runtime.manager.read_json(state["image_draft"]))
    sounds = cast(SoundDraft, runtime.manager.read_json(state["sound_draft"]))
    image_result = cast(
        ImageValidationResult,
        runtime.manager.read_json(state["image_validation_result"]),
    )
    sound_result = cast(
        SoundValidationResult,
        runtime.manager.read_json(state["sound_validation_result"]),
    )
    if image_result["status"] != "passed" or sound_result["status"] != "passed":
        raise ValueError("Only validated assets may be applied")

    package_reference = runtime.manager.write_json(
        state["project_id"],
        "game",
        "mock_package.json",
        {
            "entry": game["source_artifacts"][0],
            "images": [item["artifact"] for item in images["assets"]],
            "sounds": [item["artifact"] for item in sounds["assets"]],
        },
        producer="apply_assets_to_game",
    )
    payload: IntegratedGame = {
        "contract_version": CONTRACT_VERSION,
        "status": "integrated",
        "entry_artifact": game["source_artifacts"][0],
        "game_artifacts": [game["source_artifacts"][0], package_reference],
        "applied_image_asset_ids": image_result["validated_asset_ids"],
        "applied_sound_asset_ids": sound_result["validated_asset_ids"],
        "notes": [],
    }
    return {
        "integrated_game": runtime.manager.write_json(
            state["project_id"],
            "game",
            "integrated_game.json",
            payload,
            producer="apply_assets_to_game",
        )
    }


def mock_final_validation_node(
    state: FinalValidationAgentInput,
    runtime: MockRuntime,
) -> FinalValidationAgentOutput:
    runtime.delay("final_validation")
    spec = cast(LogicAnalysis, runtime.manager.read_json(state["logic_analysis"]))
    game = cast(IntegratedGame, runtime.manager.read_json(state["integrated_game"]))
    passed = (
        game["status"] == "integrated"
        and game["entry_artifact"] is not None
        and bool(game["applied_image_asset_ids"])
        and bool(game["applied_sound_asset_ids"])
    )
    result: FinalValidationResult = {
        "contract_version": CONTRACT_VERSION,
        "status": "passed" if passed else "failed",
        "checks": [
            {
                "criterion_id": criterion["criterion_id"],
                "passed": passed,
                "message": "Mock end-to-end requirement satisfied",
            }
            for criterion in spec["criteria"]
        ],
        "issues": [],
    }
    return {
        "final_validation_result": runtime.manager.write_json(
            state["project_id"],
            "validation",
            "final_validation_result.json",
            result,
            producer="final_validation",
        )
    }

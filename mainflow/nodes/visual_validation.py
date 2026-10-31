"""Optional visual target comparison and bounded repair Node."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import cast

from game_pipeline.unity_project_validator import UnityProjectValidator
from game_pipeline.visual_validation import (
    DEFAULT_VLM_MODEL,
    VISUAL_MODEL_ENV,
    VISUAL_PROJECT_ROOT,
    VisualValidationWorkflow,
    build_visual_target_prompt,
    visual_attempt_limit,
    visual_validation_enabled,
)
from mainflow.ArtifactManager import ArtifactManager
from mainflow.contracts import (
    CONTRACT_VERSION,
    GameLogicDraft,
    GameValidationResult,
    LogicAnalysis,
    ParsedRequest,
    VisualValidationAgentInput,
    VisualValidationAgentOutput,
    VisualValidationResult,
)
from mainflow.nodes._common import log
from MCP import ImageGenerationOptions, ImageRunResult, run_node_llm

VISUAL_TARGET_AI_ENV = "MAINFLOW_VISUAL_TARGET_AI"
VISUAL_TARGET_SIZE_ENV = "MAINFLOW_VISUAL_TARGET_SIZE"
VISUAL_TARGET_STEPS_ENV = "MAINFLOW_VISUAL_TARGET_STEPS"
DEFAULT_VISUAL_TARGET_AI = "sd_turbo"
DEFAULT_VISUAL_TARGET_SIZE = "512x288"
DEFAULT_VISUAL_TARGET_STEPS = 2


class RunNodeLLMVisualTargetGenerator:
    """Generate a comparison-only target without touching the asset backend."""

    def __init__(self, manager: ArtifactManager) -> None:
        self.manager = manager

    def generate(self, request: ParsedRequest, logic: LogicAnalysis) -> bytes:
        prompt = build_visual_target_prompt(request, logic)
        result = asyncio.run(
            run_node_llm(
                prompt,
                system_prompt=(
                    "Create one coherent gameplay reference image for visual validation only. "
                    "Do not create reusable sprites, textures, logos, captions, or a device frame."
                ),
                ai=os.environ.get(VISUAL_TARGET_AI_ENV, DEFAULT_VISUAL_TARGET_AI),
                output="image",
                image_options=ImageGenerationOptions(
                    size=os.environ.get(VISUAL_TARGET_SIZE_ENV, DEFAULT_VISUAL_TARGET_SIZE),
                    steps=int(
                        os.environ.get(
                            VISUAL_TARGET_STEPS_ENV,
                            str(DEFAULT_VISUAL_TARGET_STEPS),
                        )
                    ),
                    negative_prompt=(
                        "key art, poster, logo, watermark, caption, device frame, blurry UI, "
                        "unreadable gameplay"
                    ),
                    filename_prefix="visual_target_source",
                    artifact_category="validation",
                ),
            )
        )
        if not isinstance(result, ImageRunResult) or len(result.artifacts) != 1:
            raise RuntimeError("Visual target generation must return exactly one image artifact")
        return self.manager.read_bytes(result.artifacts[0])


# Node 계약
# - 이전 Node: apply_assets_to_game(운영) 또는 validate_game(game-test)
# - 입력 State: project_id, parsed_request, logic_analysis, game_logic_draft,
#   game_validation_result, integrated_game(운영에서만)
# - 입력 파일: game/unity_project, Visual Checklist.md
# - 출력 State: visual_validation_result(ArtifactReference)
# - 출력 파일: validation/visual_validation_result.json,
#   validation/visual/target.png, validation/visual/attempt_N.png
# - 다음 Node: final_validation
def visual_validation_node(
    state: VisualValidationAgentInput,
) -> VisualValidationAgentOutput:
    manager = ArtifactManager()
    project_id = state["project_id"]

    if not visual_validation_enabled():
        log("시각 검증 모드가 꺼져 있어 VLM 캡처/수정 단계를 건너뜁니다.")
        result: VisualValidationResult = {
            "report_version": "1.0.0",
            "contract_version": CONTRACT_VERSION,
            "mode": "disabled",
            "status": "skipped",
            "model": "none",
            "max_attempts": visual_attempt_limit(),
            "attempts": [],
            "target_image": None,
            "summary": "MAINFLOW_VISUAL_VALIDATION is disabled.",
        }
        return _write_result(manager, project_id, result)

    log("목표 화면과 Unity 캡처를 VLM으로 비교하고 최대 3회 안에서 수정합니다.")
    try:
        request = cast(ParsedRequest, manager.read_json(state["parsed_request"]))
        logic = cast(LogicAnalysis, manager.read_json(state["logic_analysis"]))
        draft = cast(GameLogicDraft, manager.read_json(state["game_logic_draft"]))
        game_validation = cast(
            GameValidationResult,
            manager.read_json(state["game_validation_result"]),
        )
        if game_validation["status"] != "passed":
            raise RuntimeError("Visual validation requires passed game validation")

        workspace_root = manager.ensure_project(project_id)
        project_root = manager.resolve_project_path(project_id, VISUAL_PROJECT_ROOT)
        required_version = UnityProjectValidator._read_project_version(project_root)
        editor = UnityProjectValidator.find_unity_editor(required_version)
        if editor is None:
            raise RuntimeError(
                "Visual validation mode requires a Unity Editor with graphical rendering support"
            )

        repository_root = Path(__file__).resolve().parents[2]

        def record_image(filename: str, content: bytes):
            return manager.write_bytes(
                project_id,
                "validation",
                filename,
                content,
                producer="visual_validation",
                media_type="image/png",
            )

        result = VisualValidationWorkflow(
            editor=editor,
            timeout_seconds=int(os.environ.get("MAINFLOW_UNITY_VALIDATION_TIMEOUT_SECONDS", "300")),
            checklist_path=repository_root / "Visual Checklist.md",
            source_docs=repository_root / "docs",
            attempts=visual_attempt_limit(),
            target_generator=RunNodeLLMVisualTargetGenerator(manager),
        ).run(
            project_root=project_root,
            workspace_root=workspace_root,
            request=request,
            logic=logic,
            draft=draft,
            record_image=record_image,
        )
    except Exception as error:  # noqa: BLE001 - persist failure at the workflow boundary
        result = {
            "report_version": "1.0.0",
            "contract_version": CONTRACT_VERSION,
            "mode": "enabled",
            "status": "failed",
            "model": os.environ.get(VISUAL_MODEL_ENV, DEFAULT_VLM_MODEL),
            "max_attempts": visual_attempt_limit(),
            "attempts": [],
            "target_image": None,
            "summary": f"{type(error).__name__}: {error}",
        }
    return _write_result(manager, project_id, result)


def _write_result(
    manager: ArtifactManager,
    project_id: str,
    result: VisualValidationResult,
) -> VisualValidationAgentOutput:
    return {
        "visual_validation_result": manager.write_json(
            project_id,
            "validation",
            "visual_validation_result.json",
            result,
            producer="visual_validation",
        )
    }

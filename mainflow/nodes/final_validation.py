"""Validate the fully integrated game against LogicAnalysis criteria."""

from __future__ import annotations

from typing import cast

from mainflow.ArtifactManager import ArtifactManager
from mainflow.contracts import (
    CONTRACT_VERSION,
    FinalValidationAgentInput,
    FinalValidationAgentOutput,
    FinalValidationResult,
    IntegratedGame,
    LogicAnalysis,
)
from mainflow.nodes._common import log


# Node 계약
# - 이전 Node: apply_assets_to_game
# - 입력 State: project_id, logic_analysis, integrated_game
# - 입력 파일: data/logic_analysis.json,
#   game/integrated_game.json 및 통합 게임 파일
# - 출력 State: final_validation_result(ArtifactReference)
# - 출력 파일: validation/final_validation_result.json
# - 다음 Node: END
def final_validation_node(
    state: FinalValidationAgentInput,
) -> FinalValidationAgentOutput:
    """Produce the final validation result for the integrated game."""
    log("LogicAnalysis의 기준으로 완성된 게임을 최종 검증합니다.")

    manager = ArtifactManager()
    cast(LogicAnalysis, manager.read_json(state["logic_analysis"]))
    integrated_game = cast(IntegratedGame, manager.read_json(state["integrated_game"]))

    # TODO: logic_analysis criteria 기준 최종 검증
    if integrated_game["status"] == "failed":
        result: FinalValidationResult = {
            "contract_version": CONTRACT_VERSION,
            "status": "failed",
            "checks": [
                {
                    "criterion_id": "integration.game_available",
                    "passed": False,
                    "message": "Game integration was skipped because game generation failed.",
                }
            ],
            "issues": [
                {
                    "code": "FINAL_GAME_UNAVAILABLE",
                    "severity": "error",
                    "message": "; ".join(integrated_game["notes"]),
                }
            ],
        }
    else:
        result = {
            "contract_version": CONTRACT_VERSION,
            "status": "pending",
            "checks": [],
            "issues": [],
        }
    return {
        "final_validation_result": manager.write_json(
            state["project_id"],
            "validation",
            "final_validation_result.json",
            result,
            producer="final_validation",
        )
    }

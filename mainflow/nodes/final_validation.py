"""Validate the fully integrated game against the initial criteria."""

from __future__ import annotations

from typing import cast

from mainflow.ArtifactManager import ArtifactManager
from mainflow.contracts import (
    CONTRACT_VERSION,
    FinalValidationAgentInput,
    FinalValidationAgentOutput,
    FinalValidationResult,
    InitialFinalValidationSpec,
    IntegratedGame,
)
from mainflow.nodes._common import log


# Node 계약
# - 이전 Node: apply_assets_to_game
# - 입력 State: project_id, initial_final_validation_spec, integrated_game
# - 입력 파일: validation/initial_final_validation_spec.json,
#   game/integrated_game.json 및 통합 게임 파일
# - 출력 State: final_validation_result(ArtifactReference)
# - 출력 파일: validation/final_validation_result.json
# - 다음 Node: END
def final_validation_node(
    state: FinalValidationAgentInput,
) -> FinalValidationAgentOutput:
    """Produce the final validation result for the integrated game."""
    log("맨 처음 생성한 최종 검증서를 기준으로 완성된 게임을 최종 검증합니다.")

    manager = ArtifactManager()
    cast(
        InitialFinalValidationSpec,
        manager.read_json(state["initial_final_validation_spec"]),
    )
    cast(IntegratedGame, manager.read_json(state["integrated_game"]))

    # TODO: initial_final_validation_spec 기준 최종 검증
    result: FinalValidationResult = {
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

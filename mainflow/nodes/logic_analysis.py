"""Convert request analysis into shared game, image, and sound requirements."""

from __future__ import annotations

from mainflow.ArtifactManager import ArtifactManager
from mainflow.contracts import (
    CONTRACT_VERSION,
    AnalysisResult,
    LogicAnalysis,
    LogicAnalysisAgentInput,
    LogicAnalysisAgentOutput,
    ParsedRequest,
    ValidationCriterion,
)
from mainflow.nodes._common import log

CORE_LOOPS = {
    "플랫포머": "이동과 점프로 구간을 돌파하고 목표 지점에 도달한다.",
    "타워 디펜스": "방어 시설을 배치하고 몰려오는 적의 경로를 차단한다.",
    "카드": "카드를 선택·사용해 자원을 관리하고 상대를 제압한다.",
    "비주얼 노벨": "이야기를 읽고 선택지를 골라 분기된 결말에 도달한다.",
    "육성 시뮬레이션": "행동을 선택해 능력치를 성장시키고 목표를 달성한다.",
    "뱀서류": "지속적으로 몰려오는 적을 상대하며 성장 선택을 반복한다.",
}


# Node 계약
# - 이전 Node: analysis
# - 입력 State: project_id, parsed_request, analysis(ArtifactReference)
# - 입력 파일: data/parsed_request.json, data/analysis.json
# - 출력 State: logic_analysis(ArtifactReference)
# - 출력 파일: data/logic_analysis.json
# - 다음 Node: design_game_logic
def logic_analysis_node(state: LogicAnalysisAgentInput) -> LogicAnalysisAgentOutput:
    """Create one authoritative requirement payload for downstream agents."""
    log("분석 결과를 공통 게임 로직과 최종 검증 기준으로 변환합니다.")

    manager = ArtifactManager()
    request: ParsedRequest = manager.read_json(state["parsed_request"])
    analysis: AnalysisResult = manager.read_json(state["analysis"])
    criteria: list[ValidationCriterion] = [
        {
            "criterion_id": f"logic-{feature['feature_id']}",
            "target": "game",
            "description": feature["description"],
            "required": True,
        }
        for feature in analysis["features"]
    ]
    criteria.extend(
        [
            {
                "criterion_id": "visual-style",
                "target": "image",
                "description": (
                    f"이미지는 {request['image_style']} 스타일과 "
                    f"{request['mood_style']} 분위기를 일관되게 표현한다."
                ),
                "required": True,
            },
            {
                "criterion_id": "sound-mood",
                "target": "sound",
                "description": f"사운드는 {request['mood_style']} 분위기와 어울린다.",
                "required": True,
            },
        ]
    )
    result: LogicAnalysis = {
        "contract_version": CONTRACT_VERSION,
        "logic_analysis_id": "logic-analysis",
        "genre": request["genre"],
        "viewpoint": request["viewpoint"],
        "mood_style": request["mood_style"],
        "core_loop": CORE_LOOPS[request["genre"]],
        "features": analysis["features"],
        "criteria": criteria,
    }
    return {
        "logic_analysis": manager.write_json(
            state["project_id"],
            "data",
            "logic_analysis.json",
            result,
            producer="logic_analysis",
        )
    }

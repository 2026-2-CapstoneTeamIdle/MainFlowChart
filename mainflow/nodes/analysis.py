"""Analyze the user's one-sentence condition into gameplay features."""

from __future__ import annotations

import re

from mainflow.ArtifactManager import ArtifactManager
from mainflow.contracts import (
    CONTRACT_VERSION,
    AnalysisAgentInput,
    AnalysisAgentOutput,
    AnalysisResult,
    FeatureRequirement,
    ParsedRequest,
)
from mainflow.nodes._common import log

FEATURE_PATTERNS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("8방향 공격", ("8방향공격", "8방향으로공격"), "8개 방향을 지정해 공격할 수 있다."),
    ("8방향 이동", ("8방향이동", "8방향으로이동"), "8개 방향으로 캐릭터를 이동할 수 있다."),
    ("자동 공격", ("자동공격",), "조건을 만족하면 공격이 자동으로 실행된다."),
    ("공격", ("공격",), "플레이어가 적 또는 목표를 공격할 수 있다."),
    ("점프", ("점프",), "플레이어가 점프할 수 있다."),
    ("성장", ("성장", "육성", "레벨업"), "플레이 결과에 따라 캐릭터가 성장한다."),
    ("카드 덱 구성", ("덱빌딩", "덱구성", "카드조합"), "카드를 선택해 덱을 구성할 수 있다."),
    ("대화 선택", ("선택지", "대화선택"), "선택한 대화에 따라 진행 결과가 달라진다."),
    ("타워 배치", ("타워배치", "방어탑배치"), "맵에 방어 시설을 배치할 수 있다."),
)

CLAUSE_SEPARATOR = re.compile(r"\s*(?:,|;|그리고|하며|면서|하고|며)\s*")


# Node 계약
# - 이전 Node: parse_input
# - 입력 State: project_id, parsed_request(ArtifactReference)
# - 입력 파일: data/parsed_request.json
# - 출력 State: analysis(ArtifactReference)
# - 출력 파일: data/analysis.json
# - 다음 Node: logic_analysis
def analysis_node(state: AnalysisAgentInput) -> AnalysisAgentOutput:
    """Extract explicit gameplay features from the user's condition sentence."""
    log("사용자 조건에서 게임 기능을 분석합니다.")

    manager = ArtifactManager()
    request: ParsedRequest = manager.read_json(state["parsed_request"])
    condition = request["condition"].strip()
    compact_condition = condition.replace(" ", "")
    features: list[FeatureRequirement] = []
    matched_names: set[str] = set()

    for name, patterns, description in FEATURE_PATTERNS:
        if any(pattern in compact_condition for pattern in patterns):
            if name == "공격" and any(
                specific in matched_names for specific in ("8방향 공격", "자동 공격")
            ):
                continue
            matched_names.add(name)
            features.append(
                {
                    "feature_id": f"feature-{len(features) + 1:02d}",
                    "name": name,
                    "description": description,
                    "source_text": condition,
                }
            )

    unmatched_clauses = _unmatched_clauses(condition)
    if not features and not unmatched_clauses:
        unmatched_clauses = [condition]
    for clause in unmatched_clauses:
        features.append(
            {
                "feature_id": f"feature-{len(features) + 1:02d}",
                "name": "사용자 지정 조건",
                "description": clause,
                "source_text": condition,
            }
        )

    result: AnalysisResult = {
        "contract_version": CONTRACT_VERSION,
        "analysis_id": "request-analysis",
        "condition_summary": condition,
        "features": features,
    }
    return {
        "analysis": manager.write_json(
            state["project_id"],
            "data",
            "analysis.json",
            result,
            producer="analysis",
        )
    }


def _unmatched_clauses(condition: str) -> list[str]:
    clauses = [clause.strip() for clause in CLAUSE_SEPARATOR.split(condition) if clause.strip()]
    unmatched: list[str] = []
    for clause in clauses:
        compact = clause.replace(" ", "")
        if any(pattern in compact for _, patterns, _ in FEATURE_PATTERNS for pattern in patterns):
            continue
        cleaned = re.sub(r"(?:이|가)?\s*가능한\s*게임$", "", clause).strip()
        if cleaned and cleaned not in unmatched:
            unmatched.append(cleaned)
    return unmatched

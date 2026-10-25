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
    ("좌우 이동", ("좌우이동", "좌우로이동"), "플레이어가 좌우로 이동할 수 있다."),
    ("8방향 공격", ("8방향공격", "8방향으로공격"), "8개 방향을 지정해 공격할 수 있다."),
    ("8방향 이동", ("8방향이동", "8방향으로이동"), "8개 방향으로 캐릭터를 이동할 수 있다."),
    ("자동 공격", ("자동공격",), "조건을 만족하면 공격이 자동으로 실행된다."),
    ("공격", ("공격",), "플레이어가 적 또는 목표를 공격할 수 있다."),
    ("점프", ("점프",), "플레이어가 점프할 수 있다."),
    (
        "벽 타기",
        ("벽타기", "벽을타", "벽타며", "벽을오르"),
        "플레이어가 벽을 감지하고 벽면을 따라 오르내릴 수 있다.",
    ),
    (
        "공중 대시",
        ("공중대시", "에어대시"),
        "플레이어가 공중에서 입력 방향으로 제한된 횟수만큼 대시할 수 있다.",
    ),
    ("성장", ("성장", "육성", "레벨업"), "플레이 결과에 따라 캐릭터가 성장한다."),
    ("카드 덱 구성", ("덱빌딩", "덱구성", "카드조합"), "카드를 선택해 덱을 구성할 수 있다."),
    ("대화 선택", ("선택지", "대화선택"), "선택한 대화에 따라 진행 결과가 달라진다."),
    ("타워 배치", ("타워배치", "방어탑배치"), "맵에 방어 시설을 배치할 수 있다."),
    (
        "체력 및 피해",
        ("health_damage", "체력감소", "체력및피해", "체력이0"),
        "적의 공격을 받으면 체력이 감소하고 0이 되면 게임 오버가 된다.",
    ),
    (
        "옵션",
        ("option", "options", "옵션", "소리조정"),
        "ESC키로 옵션을 열어 소리를 조절하거나 게임을 종료할 수 있다.",
    ),
    (
        "아이템 수집",
        ("item_collect", "아이템수집", "자원수집"),
        "게임에 필요한 자원을 수집하고 종류별로 저장한다.",
    ),
    (
        "타워 업그레이드",
        ("tower_upgrade", "타워업그레이드", "타워강화"),
        "재화를 사용해 타워의 레벨과 전투 수치를 높인다.",
    ),
    (
        "플레이어 스탯",
        ("player_stat", "player_stats", "플레이어스탯", "상태창"),
        "E키로 플레이어의 체력과 주요 스탯을 확인한다.",
    ),
    ("점수 기록", ("점수", "스코어"), "플레이 성과를 점수로 누적하고 표시한다."),
    (
        "게임 타이머",
        ("게임타이머", "제한시간", "플레이시간"),
        "경과 시간 또는 남은 시간을 측정하고 표시한다.",
    ),
    (
        "저장 및 불러오기",
        ("저장및불러오기", "세이브로드", "진행상황저장"),
        "게임 진행 상태를 저장하고 다시 불러온다.",
    ),
)

# Commas and Korean connective endings often join one coherent mechanic. Splitting on them
# produced meaningless generated features such as just "크기" or "회전속도". Dynamic code
# generation receives sentence-sized, semantically complete requirements instead.
CLAUSE_SEPARATOR = re.compile(r"\s*(?:[.!?]+|;|\r?\n)\s*")


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
    compact_condition = condition.replace(" ", "").casefold()
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
        compact = clause.replace(" ", "").casefold()
        matching_patterns = [
            pattern
            for _, patterns, _ in FEATURE_PATTERNS
            for pattern in patterns
            if pattern in compact
        ]
        # A short sentence that is fully explained by a catalogued feature needs no dynamic
        # module. A longer sentence may contain the known feature plus an unseen qualifier or
        # interaction, so preserve it as one coherent custom requirement.
        if matching_patterns and (
            len(set(matching_patterns)) >= 2
            or len(compact) <= max(len(item) for item in matching_patterns) + 12
        ):
            continue
        cleaned = re.sub(r"(?:이|가)?\s*가능한\s*게임$", "", clause).strip()
        if len(cleaned.replace(" ", "")) >= 6 and cleaned not in unmatched:
            unmatched.append(cleaned)
    return unmatched

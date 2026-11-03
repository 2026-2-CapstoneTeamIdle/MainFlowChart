"""Convert request analysis into shared game, image, and sound requirements."""

from __future__ import annotations

from typing import Any

from game_pipeline.condition_feature_analysis import (
    create_condition_feature_analyzer_from_environment,
)
from game_pipeline.design_catalog import normalize_game_spec
from game_pipeline.genre_feature_enricher import (
    create_genre_feature_enricher_from_environment,
)
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
    features = analysis["features"]
    condition_report: dict[str, object] = {
        "provider": "none",
        "model_role": "condition_feature_analysis",
        "detected_feature_count": len(features),
        "explicit_feature_count": len(features),
        "added_feature_count": 0,
        "status": "disabled",
    }
    try:
        condition_analyzer = create_condition_feature_analyzer_from_environment()
        if condition_analyzer is not None:
            log("사용자 Condition을 원자적인 구현 가능 기능으로 AI가 분해합니다.")
            condition_analysis = condition_analyzer.analyze(
                genre=request["genre"],
                viewpoint=request["viewpoint"],
                condition=request["condition"],
                detected_features=features,
            )
            features = condition_analysis.features
            condition_report = {
                **condition_analysis.report,
                "status": (
                    "partial"
                    if condition_analysis.report.get("failed_request_count", 0)
                    else "passed"
                ),
            }
            log(f"사용자 명시 기능 {len(features)}개를 설계 입력으로 확정했습니다.")
    except Exception as error:  # noqa: BLE001 - deterministic parsing remains the fallback
        condition_report = {
            **condition_report,
            "status": "failed",
            "error": f"{type(error).__name__}: {error}",
        }
        log(f"Condition AI 파싱에 실패해 정적 파싱 결과를 사용합니다: {error}")

    manager.write_json(
        state["project_id"],
        "data",
        "condition_feature_analysis.json",
        condition_report,
        producer="logic_analysis",
    )
    enrichment_report: dict[str, object] = {
        "provider": "none",
        "genre": request["genre"],
        "viewpoint": request["viewpoint"],
        "input_feature_count": len(features),
        "input_features": [
            {
                "feature_id": feature["feature_id"],
                "name": feature["name"],
                "description": feature["description"],
            }
            for feature in features
        ],
        "added_feature_count": 0,
        "dependency_feature_count": 0,
        "genre_feature_count": 0,
        "added_features": [],
        "rejected_features": [],
        "status": "disabled",
    }
    try:
        enricher = create_genre_feature_enricher_from_environment()
        if enricher is not None:
            log("명시된 기능을 바탕으로 장르 필수 기능을 AI가 보강합니다.")
            baseline = normalize_game_spec(request["genre"], {"viewpoint": request["viewpoint"]})
            enrichment = enricher.enrich(
                genre=request["genre"],
                viewpoint=request["viewpoint"],
                user_condition=request["condition"],
                core_loop=CORE_LOOPS[request["genre"]],
                existing_features=features,
                baseline_contract={
                    "features": [feature["description"] for feature in baseline["features"]],
                    "mechanics": baseline["mechanics"],
                    "controls": baseline["controls"],
                    "win_conditions": baseline["win_conditions"],
                    "lose_conditions": baseline["lose_conditions"],
                },
            )
            features = enrichment.features
            enrichment_report = {
                **enrichment.report,
                "status": (
                    "partial" if enrichment.report.get("failed_request_count", 0) else "passed"
                ),
            }
            added_count = enrichment.report["added_feature_count"]
            dependency_count = enrichment.report.get("dependency_feature_count", 0)
            genre_count = enrichment.report.get(
                "genre_feature_count", added_count - dependency_count
            )
            log(
                f"사용자 요구 의존 기능 {dependency_count}개와 장르 필수 기능 "
                f"{genre_count}개(총 {added_count}개)를 설계 입력에 추가했습니다."
            )
    except Exception as error:  # noqa: BLE001 - enrichment must not discard user requirements
        enrichment_report = {
            **enrichment_report,
            "status": "failed",
            "error": f"{type(error).__name__}: {error}",
        }
        log(f"장르 필수 기능 보강에 실패해 사용자 기능만 사용합니다: {error}")

    manager.write_json(
        state["project_id"],
        "data",
        "genre_feature_enrichment.json",
        enrichment_report,
        producer="logic_analysis",
    )
    inferred_checklists = _build_inferred_feature_checklists(features)
    manager.write_json(
        state["project_id"],
        "validation",
        "inferred_feature_checklists.json",
        {
            "contract_version": CONTRACT_VERSION,
            "checklists": inferred_checklists,
        },
        producer="logic_analysis",
    )
    manager.write_text(
        state["project_id"],
        "validation",
        "inferred_feature_checklists.md",
        _render_inferred_feature_checklists(inferred_checklists),
        producer="logic_analysis",
    )
    criteria: list[ValidationCriterion] = [
        {
            "criterion_id": f"logic-{feature['feature_id']}",
            "target": "game",
            "description": feature["description"],
            "required": True,
        }
        for feature in features
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
        "features": features,
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


def _build_inferred_feature_checklists(
    features: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    checklists: list[dict[str, Any]] = []
    for feature in features:
        origin = feature.get("origin", "user")
        checklist = feature.get("checklist")
        if origin not in {"genre_inferred", "requirement_dependency"} or not isinstance(
            checklist, dict
        ):
            continue
        checklists.append(
            {
                "checklist_id": f"IFC-{feature['feature_id']}",
                "feature_id": feature["feature_id"],
                "feature_name": feature["name"],
                "origin": origin,
                "description": feature["description"],
                "rationale": feature.get("rationale", ""),
                "acceptance_criteria": feature.get("acceptance_criteria", ""),
                "supports_feature_ids": feature.get("supports_feature_ids", []),
                "preconditions": checklist.get("preconditions", []),
                "steps": checklist.get("steps", []),
                "expected_results": checklist.get("expected_results", []),
                "failure_signals": checklist.get("failure_signals", []),
            }
        )
    return checklists


def _render_inferred_feature_checklists(checklists: list[dict[str, Any]]) -> str:
    lines = ["# AI 추론 기반 기능 체크리스트", ""]
    if not checklists:
        lines.extend(["> 이번 실행에서 추가된 기반 기능이 없습니다.", ""])
        return "\n".join(lines)
    lines.extend(
        [
            "> 사용자 입력 기능의 의존 기능과 장르 필수 기능을 생성한 직후 작성한 원본입니다.",
            "> 컴파일 이후 Feature 검증 단계에서 체크본과 검증 기록을 별도로 남깁니다.",
            "",
        ]
    )
    for item in checklists:
        lines.extend(
            [
                f"## {item['checklist_id']} · {item['feature_name']}",
                "",
                f"- Feature ID: `{item['feature_id']}`",
                f"- 출처: `{item['origin']}`",
                f"- 설명: {item['description']}",
                f"- 생성 근거: {item['rationale']}",
                f"- 최종 통과 기준: {item['acceptance_criteria']}",
            ]
        )
        if item["supports_feature_ids"]:
            lines.append(
                "- 지원하는 사용자 기능: "
                + ", ".join(f"`{value}`" for value in item["supports_feature_ids"])
            )
        for title, key in (
            ("사전 조건", "preconditions"),
            ("검증 절차", "steps"),
            ("기대 결과", "expected_results"),
            ("실패 신호", "failure_signals"),
        ):
            lines.extend(["", f"### {title}", ""])
            lines.extend(f"- [ ] {value}" for value in item[key])
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"

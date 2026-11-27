import copy

from game_pipeline.design_catalog import normalize_game_spec
from game_pipeline.design_v2 import build_design_v2
from game_pipeline.unity_project_validator import UnityProjectValidator


def test_host_validator_accepts_single_stage_and_requested_gem():
    documents = build_design_v2(
        normalize_game_spec("플랫포머"),
        "간단한 단일 스테이지 플랫포머. 발판 3개, 보석 1개와 출구를 배치한다. 적과 체크포인트는 제외한다.",
    )
    manifest = {
        "design_documents": {
            key: f"Assets/GameTemplate/Generated/Design/{key}.json" for key in documents
        }
    }
    passed, message = UnityProjectValidator._validate_design_v2_documents(
        {"design_v2": documents}, documents, manifest
    )
    assert passed, message
    invalid = copy.deepcopy(documents)
    invalid["level_plan"]["zones"][0]["collectibles"] = []
    passed, message = UnityProjectValidator._validate_design_v2_documents(
        {"design_v2": invalid}, invalid, manifest
    )
    assert not passed
    assert "requires 1 collectibles" in message


def test_host_validator_reports_mismatched_document_name():
    documents = build_design_v2(
        normalize_game_spec("플랫포머"), "간단한 단일 스테이지. 발판 3개로 구성한다."
    )
    serialized = copy.deepcopy(documents)
    serialized["game_design"]["title"] = "different"
    manifest = {
        "design_documents": {
            key: f"Assets/GameTemplate/Generated/Design/{key}.json" for key in documents
        }
    }
    passed, message = UnityProjectValidator._validate_design_v2_documents(
        {"design_v2": documents}, serialized, manifest
    )
    assert not passed
    assert "game_design" in message

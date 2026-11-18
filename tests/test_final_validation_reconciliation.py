from __future__ import annotations

from mainflow.nodes.final_validation import (
    _reconcile_upstream_game_validation,
    _runtime_transition_for_feature,
)


def test_runtime_only_game_failure_is_reconciled_after_final_unity_pass() -> None:
    checks = [
        {
            "criterion_id": "final.game_validation",
            "passed": False,
            "message": "game validation failed",
        }
    ]
    issues = [
        {
            "code": "FINAL_REQUIREMENT_UNSATISFIED",
            "severity": "error",
            "message": "Game validation must pass",
            "target_id": "final.game_validation",
        }
    ]
    upstream = {
        "issues": [
            {
                "code": "UNITY_RUNTIME_TEST_FAILED",
                "severity": "error",
                "message": "upgrade did not change state",
            },
            {
                "code": "AGENT_POST_VALIDATION_REPAIR_FAILED",
                "severity": "error",
                "message": "earlier repair budget exhausted",
            },
        ]
    }

    assert _reconcile_upstream_game_validation(checks, issues, upstream)
    assert checks[0]["passed"] is True
    assert issues == []


def test_structural_game_failure_is_not_reconciled() -> None:
    checks = [
        {
            "criterion_id": "final.game_validation",
            "passed": False,
            "message": "game validation failed",
        }
    ]
    issues = [
        {
            "code": "FINAL_REQUIREMENT_UNSATISFIED",
            "severity": "error",
            "message": "Game validation must pass",
            "target_id": "final.game_validation",
        }
    ]
    upstream = {
        "issues": [
            {
                "code": "GAME_SOURCE_ARTIFACT_INVALID",
                "severity": "error",
                "message": "source contract is invalid",
            }
        ]
    }

    assert not _reconcile_upstream_game_validation(checks, issues, upstream)
    assert checks[0]["passed"] is False
    assert len(issues) == 1


def test_survivor_attack_feature_uses_causal_damage_transition() -> None:
    assert (
        _runtime_transition_for_feature(
            {"name": "공격", "description": "플레이어의 공격 기능"},
            "SurvivorLike",
        )
        == "survivor.attack_to_damage"
    )
    assert (
        _runtime_transition_for_feature(
            {"name": "회전 검", "description": "플레이어 주변을 회전하는 검"},
            "SurvivorLike",
        )
        == "survivor.attack_to_damage"
    )
    assert (
        _runtime_transition_for_feature(
            {"name": "체력 및 피해", "description": "적의 공격을 받으면 체력이 감소한다"},
            "SurvivorLike",
        )
        is None
    )

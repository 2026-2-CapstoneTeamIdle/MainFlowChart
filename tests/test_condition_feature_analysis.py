from __future__ import annotations

import unittest
from collections.abc import Mapping
from typing import Any
from unittest.mock import patch

from game_pipeline.condition_feature_analysis import (
    CONDITION_FEATURE_SCHEMA,
    ConditionFeatureAnalyzer,
)
from mainflow.contracts import FeatureRequirement


class FakeStructuredClient:
    def __init__(self, response: Mapping[str, Any] | list[Mapping[str, Any]]) -> None:
        self.responses = response if isinstance(response, list) else [response]
        self.prompts: list[str] = []
        self.schema: Mapping[str, Any] = {}

    def generate_json(self, prompt: str, schema: Mapping[str, Any]) -> Mapping[str, Any]:
        self.prompts.append(prompt)
        self.schema = schema
        return self.responses[len(self.prompts) - 1]


class ConditionFeatureAnalysisTest(unittest.TestCase):
    def test_first_analysis_returns_project_title_alongside_features(self) -> None:
        client = FakeStructuredClient(
            {
                "project_name": "  별빛   산책  ",
                "features": [
                    {
                        "name": "플레이어 이동",
                        "description": "플레이어가 이동한다.",
                        "source_text": "플레이어가 이동한다",
                        "acceptance_criteria": "방향 입력으로 이동한다.",
                        "acceptance_items": ["방향 입력으로 이동한다."],
                        "implementation_kind": "generate_code",
                    }
                ],
            }
        )
        result = ConditionFeatureAnalyzer(client, "codex_cli").analyze(
            genre="플랫포머",
            viewpoint="사이드뷰",
            condition="플레이어가 이동한다.",
            detected_features=[],
        )
        self.assertEqual(result.report["project_name"], "별빛 산책")
        self.assertIn("project_name", client.schema["required"])
        self.assertIn("project_name", client.schema["properties"])
        self.assertEqual(len(client.prompts), 1)
        self.assertIn("ENTIRE full_condition", client.prompts[0])

    def test_undercovered_group_falls_back_to_original_condition(self) -> None:
        condition = (
            "플레이어는 이동한다. 적이 추격한다. 적이 사망하면 보석을 떨어뜨린다. "
            "보석을 획득하면 경험치가 증가한다."
        )
        client = FakeStructuredClient(
            {
                "features": [
                    {
                        "name": "플레이어 이동",
                        "description": "플레이어가 방향 입력에 따라 이동한다.",
                        "source_text": "플레이어는 이동한다",
                        "acceptance_criteria": "플레이어가 이동한다.",
                        "acceptance_items": ["플레이어가 이동한다."],
                        "implementation_kind": "generate_code",
                    }
                ]
            }
        )
        result = ConditionFeatureAnalyzer(client, "codex_cli").analyze(
            genre="뱀서류",
            viewpoint="탑다운",
            condition=condition,
            detected_features=[],
        )
        self.assertEqual(result.report["failed_request_count"], 1)
        self.assertIn("보석을 획득하면 경험치가 증가한다", result.features[0]["source_text"])

    def test_group_overlapping_detected_feature_keeps_all_rules(self) -> None:
        client = FakeStructuredClient(
            {
                "features": [
                    {
                        "name": "체력 및 피해",
                        "description": "체력, 피격 무적과 사망 상태를 관리한다.",
                        "source_text": "최대 체력은 100이고 피격 후 1초 동안 무적이다",
                        "acceptance_criteria": "체력과 무적 및 사망 상태가 동작한다.",
                        "acceptance_items": [
                            "시작 체력은 100이다.",
                            "피격 후 1초 동안 무적이다.",
                            "체력 0이면 게임 오버가 된다.",
                        ],
                        "implementation_kind": "generate_code",
                    }
                ]
            }
        )
        result = ConditionFeatureAnalyzer(client, "codex_cli").analyze(
            genre="뱀서류",
            viewpoint="탑다운",
            condition="최대 체력은 100이고 피격 후 1초 동안 무적이다.",
            detected_features=[
                {
                    "feature_id": "feature-01",
                    "name": "체력 및 피해",
                    "description": "플레이어의 체력이 피격 시 감소한다.",
                    "source_text": "최대 체력은 100이고 피격 후 1초 동안 무적이다.",
                }
            ],
        )
        self.assertEqual(len(result.features), 1)
        self.assertEqual(len(result.features[0]["acceptance_items"]), 3)
        self.assertEqual(result.report["merged_feature_count"], 1)

    def test_codex_groups_related_rules_without_discarding_acceptance_items(self) -> None:
        condition = (
            "플레이어는 8방향으로 이동하고 최대 체력 100으로 시작한다. "
            "피격 후 1초 동안 무적이며 체력이 0이면 게임 오버가 된다. "
            "검은 플레이어 주변을 회전하며 적에게 피해를 준다. "
            "검은 투사체로 대체하면 안 되고 적마다 피격 쿨다운이 적용된다."
        )
        client = FakeStructuredClient(
            {
                "features": [
                    {
                        "name": "플레이어 이동과 생존",
                        "description": "이동, 체력, 피격과 게임 오버를 관리한다.",
                        "source_text": "플레이어는 8방향으로 이동하고 최대 체력 100으로 시작한다",
                        "acceptance_criteria": "이동과 피해 및 사망 상태가 실제 플레이에 반영된다.",
                        "acceptance_items": [
                            "플레이어는 8방향으로 이동한다.",
                            "최대 체력과 시작 체력은 100이다.",
                            "피격 후 1초 동안 무적이다.",
                            "체력이 0이면 게임 오버가 된다.",
                        ],
                        "implementation_kind": "generate_code",
                    },
                    {
                        "name": "회전 검 전투",
                        "description": "회전 검으로 적을 공격한다.",
                        "source_text": "검은 플레이어 주변을 회전하며 적에게 피해를 준다",
                        "acceptance_criteria": "회전 검의 충돌과 피해가 동작한다.",
                        "acceptance_items": [
                            "검은 플레이어 주변을 회전한다.",
                            "검이 적에게 피해를 준다.",
                            "검을 투사체로 대체하면 안 된다.",
                            "동일 적에게 피격 쿨다운이 적용된다.",
                        ],
                        "implementation_kind": "generate_code",
                    },
                ]
            }
        )

        result = ConditionFeatureAnalyzer(client, "codex_cli").analyze(
            genre="뱀서류",
            viewpoint="탑다운",
            condition=condition,
            detected_features=[],
        )

        self.assertEqual(len(client.prompts), 1)
        self.assertEqual(len(result.features), 2)
        self.assertEqual(result.report["acceptance_item_count"], 8)
        self.assertIn("투사체로 대체하면 안 된다", result.features[1]["acceptance_items"][2])
        self.assertIn("Group clauses", client.prompts[0])

    def test_preserves_successful_segments_when_one_request_fails(self) -> None:
        class PartialClient:
            def __init__(self) -> None:
                self.calls = 0

            def generate_json(self, prompt: str, schema: Mapping[str, Any]) -> Mapping[str, Any]:
                self.calls += 1
                if self.calls == 1:
                    raise RuntimeError("token limit")
                return {
                    "features": [
                        {
                            "name": "보석 수집 완료",
                            "description": "모든 보석을 모으면 목표 지점이 활성화된다.",
                            "source_text": "보석을 모두 모으면 목표가 열린다",
                            "acceptance_criteria": "마지막 보석 수집 후 목표가 활성화된다.",
                            "implementation_kind": "scene_binding",
                        }
                    ]
                }

        result = ConditionFeatureAnalyzer(PartialClient(), "test").analyze(
            genre="플랫포머",
            viewpoint="사이드뷰",
            condition="가시에 닿으면 체력이 감소한다. 보석을 모두 모으면 목표가 열린다.",
            detected_features=[],
        )

        self.assertEqual(
            [feature["name"] for feature in result.features],
            ["보석 수집 완료", "사용자 지정 조건"],
        )
        self.assertIn("가시에 닿으면", result.features[1]["description"])
        self.assertEqual(result.report["successful_request_count"], 1)
        self.assertEqual(result.report["failed_request_count"], 1)
        self.assertEqual(result.report["failed_segments"][0]["segment_index"], 1)

    def test_retains_unprocessed_custom_clauses_when_feature_limit_is_reached(self) -> None:
        client = FakeStructuredClient(
            {
                "features": [
                    {
                        "name": "가시 피해",
                        "description": "플레이어가 가시에 닿으면 체력이 감소한다.",
                        "source_text": "가시에 닿으면 체력이 감소한다",
                        "acceptance_criteria": "가시 접촉 전후 플레이어 체력이 감소한다.",
                        "implementation_kind": "configure_existing",
                    }
                ]
            }
        )
        detected: list[FeatureRequirement] = [
            {
                "feature_id": "feature-01",
                "name": "사용자 지정 조건",
                "description": "가시에 닿으면 체력이 감소한다",
                "source_text": "가시에 닿으면 체력이 감소한다. 보석을 모으면 문이 열린다.",
            },
            {
                "feature_id": "feature-02",
                "name": "사용자 지정 조건",
                "description": "보석을 모으면 문이 열린다",
                "source_text": "가시에 닿으면 체력이 감소한다. 보석을 모으면 문이 열린다.",
            },
        ]

        with patch("game_pipeline.condition_feature_analysis.MAX_EXPLICIT_FEATURES", 1):
            result = ConditionFeatureAnalyzer(client, "test").analyze(
                genre="플랫포머",
                viewpoint="사이드뷰",
                condition="가시에 닿으면 체력이 감소한다. 보석을 모으면 문이 열린다.",
                detected_features=detected,
            )

        self.assertEqual(len(client.prompts), 1)
        self.assertEqual(
            [item["name"] for item in result.features], ["가시 피해", "사용자 지정 조건"]
        )
        self.assertEqual(result.features[1]["description"], "보석을 모으면 문이 열린다")
        self.assertEqual(result.report["truncated_segment_count"], 1)
        self.assertEqual(result.report["retained_fallback_feature_count"], 1)

    def test_replaces_vague_custom_clause_with_atomic_user_features(self) -> None:
        client = FakeStructuredClient(
            {
                "features": [
                    {
                        "name": "순찰 적",
                        "description": "적이 지정된 구간을 왕복 순찰한다.",
                        "source_text": "맵에는 순찰하는 적이 있다",
                        "acceptance_criteria": "Play Mode에서 적의 이동 방향이 경계에서 반전된다.",
                        "implementation_kind": "generate_code",
                    },
                    {
                        "name": "버튼 구간 개방",
                        "description": "플레이어가 버튼에 닿으면 막힌 구간이 열린다.",
                        "source_text": "버튼에 닿으면 막힌 구간이 열린다",
                        "acceptance_criteria": "버튼 접촉 전후에 차단 오브젝트가 비활성화된다.",
                        "implementation_kind": "scene_binding",
                    },
                ]
            }
        )
        detected: list[FeatureRequirement] = [
            {
                "feature_id": "feature-01",
                "name": "점프",
                "description": "플레이어가 점프할 수 있다.",
                "source_text": "점프하고 순찰하는 적과 버튼이 있는 게임",
            },
            {
                "feature_id": "feature-02",
                "name": "사용자 지정 조건",
                "description": "순찰하는 적과 버튼이 있는 게임",
                "source_text": "점프하고 순찰하는 적과 버튼이 있는 게임",
            },
        ]

        result = ConditionFeatureAnalyzer(client, "test").analyze(
            genre="플랫포머",
            viewpoint="사이드뷰",
            condition="점프하고 맵에는 순찰하는 적이 있으며 버튼에 닿으면 막힌 구간이 열린다",
            detected_features=detected,
        )

        self.assertEqual(
            [item["name"] for item in result.features], ["점프", "순찰 적", "버튼 구간 개방"]
        )
        self.assertNotIn("사용자 지정 조건", [item["name"] for item in result.features])
        self.assertEqual(result.features[1]["origin"], "user")
        self.assertIn("Play Mode", result.features[1]["acceptance_criteria"])
        self.assertIs(client.schema, CONDITION_FEATURE_SCHEMA)
        self.assertIn("Decompose EVERY", client.prompts[0])

    def test_splits_multi_sentence_condition_into_bounded_requests(self) -> None:
        client = FakeStructuredClient(
            [
                {
                    "features": [
                        {
                            "name": "가시 피해",
                            "description": "플레이어가 가시에 닿으면 체력이 감소한다.",
                            "source_text": "가시에 닿으면 체력이 감소한다",
                            "acceptance_criteria": "가시 접촉 전후 플레이어 체력이 감소한다.",
                            "implementation_kind": "configure_existing",
                        }
                    ]
                },
                {
                    "features": [
                        {
                            "name": "보석 수집 완료",
                            "description": "모든 보석을 모으면 목표 지점이 활성화된다.",
                            "source_text": "보석을 모두 모으면 목표가 열린다",
                            "acceptance_criteria": "마지막 보석 수집 후 목표 오브젝트가 활성화된다.",
                            "implementation_kind": "scene_binding",
                        }
                    ]
                },
            ]
        )

        result = ConditionFeatureAnalyzer(client, "test").analyze(
            genre="플랫포머",
            viewpoint="사이드뷰",
            condition="가시에 닿으면 체력이 감소한다. 보석을 모두 모으면 목표가 열린다.",
            detected_features=[],
        )

        self.assertEqual(len(client.prompts), 2)
        self.assertEqual(result.report["request_count"], 2)
        self.assertEqual(
            [feature["name"] for feature in result.features], ["가시 피해", "보석 수집 완료"]
        )
        self.assertIn('"segment_index":1', client.prompts[0])
        self.assertIn('"segment_index":2', client.prompts[1])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest
from collections.abc import Mapping
from typing import Any

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

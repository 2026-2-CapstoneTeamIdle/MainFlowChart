from __future__ import annotations

import os
import tempfile
import unittest
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any
from unittest.mock import patch

from game_pipeline.feature_planner import plan_feature_mechanics
from game_pipeline.genre_feature_enricher import (
    GENRE_FEATURE_ENRICHMENT_SCHEMA,
    GenreFeatureEnricher,
    GenreFeatureEnrichment,
    create_genre_feature_enricher_from_environment,
)
from mainflow.ArtifactManager import ArtifactManager
from mainflow.contracts import FeatureRequirement
from mainflow.nodes.analysis import analysis_node
from mainflow.nodes.logic_analysis import logic_analysis_node
from mainflow.nodes.parse_input import parse_input_node


class FakeStructuredClient:
    def __init__(self, response: Mapping[str, Any]) -> None:
        self.response = response
        self.prompts: list[str] = []
        self.schema: Mapping[str, Any] = {}

    def generate_json(self, prompt: str, schema: Mapping[str, Any]) -> Mapping[str, Any]:
        self.prompts.append(prompt)
        self.schema = schema
        response = deepcopy(self.response)
        for feature in response.get("features", []):
            feature.setdefault(
                "checklist",
                {
                    "preconditions": ["Play Mode에서 필요한 actor와 초기 상태가 존재한다."],
                    "steps": ["기능을 발생시키는 입력 또는 시간 경과를 실행한다."],
                    "expected_results": [feature["acceptance_criteria"]],
                    "failure_signals": ["요청한 상태 변화가 관찰되지 않는다."],
                },
            )
        return response


class GenreFeatureEnricherTest(unittest.TestCase):
    def test_adds_missing_genre_features_and_preserves_user_features(self) -> None:
        client = FakeStructuredClient(
            {
                "features": [
                    {
                        "name": "자동 공격",
                        "description": "플레이어가 적을 자동으로 공격한다.",
                        "rationale": "이미 사용자가 요청한 기능이다.",
                        "acceptance_criteria": "적이 피해를 받는다.",
                        "closure_kind": "user_requirement_dependency",
                        "supports_feature_ids": ["feature-01"],
                        "dependency_role": "runtime_binding",
                        "implementation_kind": "reuse_module",
                        "target_mechanics": ["auto_attack"],
                    },
                    {
                        "name": "적 추적",
                        "description": "적이 지속적으로 생성되어 플레이어를 추적한다.",
                        "rationale": "장르의 기본 적 행동이다.",
                        "acceptance_criteria": "적이 생성되어 플레이어 방향으로 이동한다.",
                        "closure_kind": "genre_core_requirement",
                        "supports_feature_ids": [],
                        "dependency_role": "genre_core",
                        "implementation_kind": "reuse_module",
                        "target_mechanics": ["enemy_spawn", "chase_ai"],
                    },
                    {
                        "name": "자동 공격 피해 연결",
                        "description": "자동 공격의 타격 판정이 대상의 체력을 실제로 감소시킨다.",
                        "rationale": "공격 시각 표현만으로는 요청된 전투가 성립하지 않는다.",
                        "acceptance_criteria": (
                            "Play Mode에서 자동 공격 전후의 동일한 적 체력을 비교하면 감소한다."
                        ),
                        "closure_kind": "user_requirement_dependency",
                        "supports_feature_ids": ["feature-01"],
                        "dependency_role": "interaction_consequence",
                        "implementation_kind": "scene_binding",
                        "target_mechanics": ["health_damage"],
                    },
                    {
                        "name": "상시 체력 HUD",
                        "description": "현재 체력과 최대 체력이 플레이 중 항상 화면에 표시된다.",
                        "rationale": "접촉 피해의 결과를 사용자가 즉시 확인해야 한다.",
                        "acceptance_criteria": (
                            "Play Mode 첫 프레임부터 HP가 보이고 피해 후 같은 값으로 갱신된다."
                        ),
                        "closure_kind": "genre_core_requirement",
                        "supports_feature_ids": [],
                        "dependency_role": "genre_core",
                        "implementation_kind": "scene_binding",
                        "target_mechanics": ["health_damage"],
                    },
                    {
                        "name": "재시작 흐름",
                        "description": "플레이어 사망 후 게임을 다시 시작할 수 있다.",
                        "rationale": "도달 가능한 패배 상태에는 복구 가능한 흐름이 필요하다.",
                        "acceptance_criteria": (
                            "사망 화면의 재시작 입력이 체력과 전투 상태를 초기화한다."
                        ),
                        "closure_kind": "genre_core_requirement",
                        "supports_feature_ids": [],
                        "dependency_role": "genre_core",
                        "implementation_kind": "configure_existing",
                        "target_mechanics": ["scene_flow"],
                    },
                ]
            }
        )
        existing: list[FeatureRequirement] = [
            {
                "feature_id": "feature-01",
                "name": "자동 공격",
                "description": "플레이어가 적을 자동으로 공격한다.",
                "source_text": "적을 자동 공격한다.",
            }
        ]

        result = GenreFeatureEnricher(client, "test").enrich(
            genre="뱀서류",
            viewpoint="탑다운",
            user_condition="적을 자동 공격하는 생존 게임",
            core_loop="몰려오는 적을 상대하며 성장한다.",
            existing_features=existing,
            baseline_contract={
                "features": ["적이 지속적으로 생성되어 플레이어를 추적한다."],
                "mechanics": ["enemy_spawn", "chase_ai"],
            },
        )

        self.assertEqual(result.features[0], existing[0])
        self.assertEqual(
            [feature["name"] for feature in result.features[1:]],
            ["자동 공격 피해 연결", "상시 체력 HUD", "재시작 흐름"],
        )
        self.assertEqual(result.features[1]["origin"], "requirement_dependency")
        self.assertEqual(result.features[1]["supports_feature_ids"], ["feature-01"])
        self.assertIn("Play Mode", result.features[1]["acceptance_criteria"])
        self.assertTrue(result.features[1]["checklist"]["steps"])
        self.assertEqual(result.report["added_feature_count"], 3)
        self.assertEqual(result.report["dependency_feature_count"], 1)
        self.assertEqual(result.report["genre_feature_count"], 2)
        self.assertGreaterEqual(len(result.report["rejected_features"]), 2)
        self.assertEqual(result.report["request_count"], 2)
        self.assertEqual(len(client.prompts), 2)
        self.assertIs(client.schema, GENRE_FEATURE_ENRICHMENT_SCHEMA)
        self.assertTrue(all("already_required_features" in prompt for prompt in client.prompts))
        self.assertTrue(
            all("already_implemented_genre_baseline" in prompt for prompt in client.prompts)
        )
        self.assertIn("user_requirement_dependency", client.prompts[0])
        self.assertIn("playable game rather than a disconnected simulation", client.prompts[1])
        self.assertTrue(
            all("observable before/after change" in prompt for prompt in client.prompts)
        )

        plan = plan_feature_mechanics(result.features, "뱀서류")
        dependency = next(
            feature
            for feature in plan.game_features
            if feature.get("origin") == "requirement_dependency"
        )
        self.assertEqual(dependency["supports_feature_ids"], ["feature-01"])
        self.assertEqual(dependency["dependency_role"], "interaction_consequence")
        self.assertIn("acceptance_criteria", dependency)
        generated_requirement = next(iter(plan.generation_requirements.values()))
        self.assertIn(
            "타격 판정이 대상의 체력을 실제로 감소", generated_requirement["must_preserve"]
        )
        self.assertIn("자동 공격 전후", generated_requirement["acceptance_criteria"])

    def test_offline_default_does_not_connect_to_localai(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(create_genre_feature_enricher_from_environment())

    def test_explicit_off_disables_enrichment(self) -> None:
        with patch.dict(
            os.environ,
            {"MAINFLOW_GENRE_FEATURE_PROVIDER": "off"},
            clear=True,
        ):
            self.assertIsNone(create_genre_feature_enricher_from_environment())

    def test_logic_analysis_publishes_enriched_features_for_downstream_design(self) -> None:
        class StubEnricher:
            def enrich(self, **kwargs: Any) -> GenreFeatureEnrichment:
                existing = kwargs["existing_features"]
                inferred: FeatureRequirement = {
                    "feature_id": "genre-required-01",
                    "name": "상시 체력 HUD",
                    "description": "현재 체력과 최대 체력이 플레이 중 항상 화면에 표시된다.",
                    "source_text": "장르 필수 기능 추론",
                    "origin": "genre_inferred",
                    "rationale": "피해 결과를 확인해야 한다.",
                    "acceptance_criteria": "Play Mode에서 HP가 항상 표시된다.",
                    "checklist": {
                        "preconditions": ["플레이어 체력이 양수로 초기화된다."],
                        "steps": ["Play Mode를 시작하고 플레이어에게 피해를 준다."],
                        "expected_results": ["HP UI가 감소한 현재 체력을 표시한다."],
                        "failure_signals": ["피해 후에도 HP UI 값이 변하지 않는다."],
                    },
                    "implementation_kind": "scene_binding",
                    "target_mechanics": ["health_damage"],
                }
                return GenreFeatureEnrichment(
                    features=[*existing, inferred],
                    report={
                        "provider": "stub",
                        "genre": kwargs["genre"],
                        "viewpoint": kwargs["viewpoint"],
                        "input_feature_count": len(existing),
                        "input_features": [],
                        "added_feature_count": 1,
                        "added_features": [],
                        "rejected_features": [],
                    },
                )

        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory) / "workspace"
            with (
                patch.dict(os.environ, {"MAINFLOW_WORKSPACE": str(workspace)}),
                patch(
                    "mainflow.nodes.logic_analysis.create_genre_feature_enricher_from_environment",
                    return_value=StubEnricher(),
                ),
            ):
                state = parse_input_node(
                    {
                        "image_style": "Pixel Art",
                        "mood_style": "Fantasy",
                        "genre": "뱀서류",
                        "viewpoint": "탑다운",
                        "condition": "플레이어가 적을 자동으로 공격한다.",
                    }
                )
                state.update(analysis_node(state))  # type: ignore[arg-type]
                state.update(logic_analysis_node(state))  # type: ignore[arg-type]
                manager = ArtifactManager()
                logic = manager.read_json(state["logic_analysis"])
                report_reference = next(
                    reference
                    for reference in manager.list_artifacts(state["project_id"])
                    if reference["relative_path"] == "data/genre_feature_enrichment.json"
                )
                report = manager.read_json(report_reference)
                checklist_json_reference = next(
                    reference
                    for reference in manager.list_artifacts(state["project_id"])
                    if reference["relative_path"] == "validation/inferred_feature_checklists.json"
                )
                checklist_markdown_reference = next(
                    reference
                    for reference in manager.list_artifacts(state["project_id"])
                    if reference["relative_path"] == "validation/inferred_feature_checklists.md"
                )
                checklist_payload = manager.read_json(checklist_json_reference)
                checklist_markdown = manager.read_text(checklist_markdown_reference)

        self.assertIn("상시 체력 HUD", [feature["name"] for feature in logic["features"]])
        self.assertIn(
            "logic-genre-required-01",
            [criterion["criterion_id"] for criterion in logic["criteria"]],
        )
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["added_feature_count"], 1)
        self.assertEqual(
            checklist_payload["checklists"][0]["feature_id"],
            "genre-required-01",
        )
        self.assertIn("HP UI가 감소한 현재 체력", checklist_markdown)


if __name__ == "__main__":
    unittest.main()

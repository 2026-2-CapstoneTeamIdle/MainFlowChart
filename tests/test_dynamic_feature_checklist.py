from __future__ import annotations

import tempfile
import unittest
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from game_pipeline.dynamic_feature_checklist import (
    CHECKLIST_BATCH_COUNT,
    CHECKLIST_BATCH_SIZE,
    CHECKLIST_ITEM_COUNT,
    TEST_METHOD_BATCH_COUNT,
    TEST_METHOD_BATCH_SIZE,
    DynamicFeatureChecklistGenerator,
    UnityChecklistTestGenerator,
    load_generated_checklist,
    persist_generated_checklist,
    persist_generated_feature_test,
)
from game_pipeline.feature_checklist_validation import FeatureChecklistWorkflow
from mainflow.contracts import LogicAnalysis


class FakeStructuredClient:
    def __init__(self, response: Mapping[str, Any]) -> None:
        self.response = response
        self.prompts: list[str] = []

    def generate_json(self, prompt: str, _schema: Mapping[str, Any]) -> Mapping[str, Any]:
        self.prompts.append(prompt)
        criteria = self.response.get("criteria")
        if isinstance(criteria, list) and len(criteria) == CHECKLIST_ITEM_COUNT:
            batch_index = (len(self.prompts) - 1) % CHECKLIST_BATCH_COUNT
            start = batch_index * CHECKLIST_BATCH_SIZE
            return {**self.response, "criteria": criteria[start : start + CHECKLIST_BATCH_SIZE]}
        methods = self.response.get("methods")
        if isinstance(methods, list) and len(methods) == CHECKLIST_ITEM_COUNT:
            batch_index = (len(self.prompts) - 1) % TEST_METHOD_BATCH_COUNT
            start = batch_index * TEST_METHOD_BATCH_SIZE
            return {
                **self.response,
                "methods": methods[start : start + TEST_METHOD_BATCH_SIZE],
            }
        return self.response


def _logic_analysis() -> LogicAnalysis:
    return {
        "contract_version": "1.0.0",
        "logic_analysis_id": "logic-test",
        "genre": "플랫포머",
        "viewpoint": "사이드뷰",
        "mood_style": "Fantasy",
        "core_loop": "이동과 점프로 목표에 도달한다.",
        "features": [
            {
                "feature_id": "feature-01",
                "name": "점프",
                "description": "플레이어가 점프한다.",
                "source_text": "점프 게임",
                "origin": "user",
            },
            {
                "feature_id": "requirement-dependency-01",
                "name": "지면 판정",
                "description": "지면에서만 점프를 시작한다.",
                "source_text": "점프 의존 기능",
                "origin": "requirement_dependency",
            },
        ],
        "criteria": [],
    }


class DynamicFeatureChecklistTest(unittest.TestCase):
    def test_repository_checklists_each_have_thirty_items(self) -> None:
        docs = Path(__file__).resolve().parents[1] / "docs"
        paths = sorted(docs.glob("*Validator Checklist*.md"))
        self.assertEqual(len(paths), 17)
        for path in paths:
            item_count = sum(
                line.strip().startswith("- [ ]")
                for line in path.read_text(encoding="utf-8").splitlines()
            )
            self.assertEqual(item_count, 30, path.name)

    def test_generates_one_thirty_item_checklist_and_test_file_per_feature(self) -> None:
        criteria = [
            {
                "feature_ids": [
                    "feature-01",
                    "requirement-dependency-01",
                ],
                "title": f"점프 검증 {index}",
                "category": "runtime",
                "setup": "플레이어와 지면을 생성한다.",
                "action": "점프 입력을 한 번 보낸다.",
                "expected": "플레이어의 수직 위치가 증가한다.",
                "evidence": "Rigidbody2D 위치 전후 비교",
            }
            for index in range(1, CHECKLIST_ITEM_COUNT + 1)
        ]
        checklist_client = FakeStructuredClient({"criteria": criteria})
        checklist = DynamicFeatureChecklistGenerator(checklist_client, "test").generate(
            project_id="20261102_01",
            logic_analysis=_logic_analysis(),
            source_root=Path("missing"),
        )
        self.assertEqual(len(checklist_client.prompts), 2 * CHECKLIST_BATCH_COUNT)
        self.assertTrue(all("EXACTLY 10" in prompt for prompt in checklist_client.prompts))
        self.assertIn('"index":1', checklist_client.prompts[0])
        self.assertIn('"index":3', checklist_client.prompts[2])
        self.assertEqual(len(checklist.feature_checklists), 2)
        self.assertEqual(len(checklist.criteria), 60)
        self.assertTrue(all(len(item.criteria) == 30 for item in checklist.feature_checklists))
        self.assertEqual(
            [item.feature_id for item in checklist.feature_checklists],
            ["feature-01", "requirement-dependency-01"],
        )

        generated_sources: dict[str, str] = {}
        for feature_checklist in checklist.feature_checklists:
            methods = [
                {
                    "criterion_id": criterion.criterion_id,
                    "source_code": (
                        "[UnityTest]\n"
                        f"public IEnumerator {criterion.criterion_id}_Check() "
                        "{ yield return null; Assert.That(true); }"
                    ),
                }
                for criterion in feature_checklist.criteria
            ]
            test_client = FakeStructuredClient({"methods": methods})
            generated_sources[feature_checklist.feature_id] = UnityChecklistTestGenerator(
                test_client, "test"
            ).generate(
                checklist=feature_checklist,
                project_root=Path("missing"),
                feedback="previous compiler diagnostic",
            )
            self.assertEqual(len(test_client.prompts), TEST_METHOD_BATCH_COUNT)
            self.assertTrue(all("EXACTLY 10" in prompt for prompt in test_client.prompts))
            self.assertTrue(all("runtime_api_contract" in prompt for prompt in test_client.prompts))
            self.assertTrue(
                all("available_runtime_sources" not in prompt for prompt in test_client.prompts)
            )

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            workspace = root / "workspace" / "20261102_01"
            project = workspace / "game" / "unity_project"
            persist_generated_checklist(
                checklist,
                workspace_root=workspace,
                project_root=project,
            )
            for feature_checklist in checklist.feature_checklists:
                persist_generated_feature_test(
                    feature_checklist,
                    workspace_root=workspace,
                    project_root=project,
                    source_code=generated_sources[feature_checklist.feature_id],
                )
            restored = load_generated_checklist(workspace)
            self.assertIsNotNone(restored)
            self.assertEqual(len(restored.feature_checklists), 2)  # type: ignore[union-attr]
            self.assertEqual(len(restored.criteria), 60)  # type: ignore[union-attr]
            for feature_checklist in checklist.feature_checklists:
                self.assertTrue(
                    (
                        workspace
                        / "validation/feature_checklists/generated"
                        / feature_checklist.feature_id
                        / "checklist.json"
                    ).is_file()
                )
                self.assertTrue(
                    (project / "Assets/Tests/PlayMode" / feature_checklist.test_filename).is_file()
                )

    def test_dynamic_skips_and_missing_tests_are_failures(self) -> None:
        criteria = [
            {
                "feature_ids": ["feature-01", "requirement-dependency-01"],
                "title": f"점프 검증 {index}",
                "category": "runtime",
                "setup": "플레이어와 지면을 생성한다.",
                "action": "점프 입력을 보낸다.",
                "expected": "플레이어가 상승한다.",
                "evidence": "위치 전후 비교",
            }
            for index in range(1, CHECKLIST_ITEM_COUNT + 1)
        ]
        checklist = DynamicFeatureChecklistGenerator(
            FakeStructuredClient({"criteria": criteria}), "test"
        ).generate(
            project_id="20261102_01",
            logic_analysis=_logic_analysis(),
            source_root=Path("missing"),
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            report = Path(temporary_directory) / "results.xml"
            root = ET.Element("test-run")
            suite = ET.SubElement(root, "test-suite")
            ET.SubElement(
                suite,
                "test-case",
                {
                    "fullname": "GeneratedFeatureChecklist_DFC001.DFC001_01_Check",
                    "result": "Skipped",
                    "label": "Ignored",
                },
            )
            ET.ElementTree(root).write(report, encoding="utf-8", xml_declaration=True)
            results = FeatureChecklistWorkflow._parse_nunit(report, checklist)

        self.assertEqual(results[0].feature_id, "DFC001_01")
        self.assertEqual(results[0].status, "failed")
        self.assertEqual(len(results), 60)
        self.assertTrue(all(item.status == "error" for item in results[1:]))

    def test_unity_test_prompt_uses_compact_public_api_contract(self) -> None:
        criteria = [
            {
                "feature_ids": ["feature-01", "requirement-dependency-01"],
                "title": f"점프 API 검증 {index}",
                "category": "runtime",
                "setup": "플레이어를 생성한다.",
                "action": "점프를 호출한다.",
                "expected": "수직 속도가 증가한다.",
                "evidence": "공개 속성을 읽는다.",
            }
            for index in range(1, CHECKLIST_ITEM_COUNT + 1)
        ]
        checklist = (
            DynamicFeatureChecklistGenerator(FakeStructuredClient({"criteria": criteria}), "test")
            .generate(
                project_id="20261103_01",
                logic_analysis=_logic_analysis(),
                source_root=Path("missing"),
            )
            .feature_checklists[0]
        )
        methods = [
            {
                "criterion_id": criterion.criterion_id,
                "source_code": (
                    "[UnityTest]\n"
                    f"public IEnumerator {criterion.criterion_id}_Check() "
                    "{ yield return null; Assert.That(true); }"
                ),
            }
            for criterion in checklist.criteria
        ]

        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory)
            runtime = project / "Assets/GameTemplate/Runtime/Platformer"
            runtime.mkdir(parents=True)
            (runtime / "PlatformerMovementModule.cs").write_text(
                """namespace TeamIdle.GameTemplate.Runtime
{
    public class PlatformerMovementModule
    {
        public override string ModuleId => \"platformer_movement\";
        public float VerticalSpeed { get; set; }
        public void Jump() { }
        private string SecretImplementation() => \"PRIVATE_SENTINEL\";
    }
}
""",
                encoding="utf-8",
            )
            client = FakeStructuredClient({"methods": methods})
            UnityChecklistTestGenerator(client, "test").generate(
                checklist=checklist,
                project_root=project,
            )

        combined_prompt = "\n".join(client.prompts)
        self.assertIn("Jump", combined_prompt)
        self.assertIn("VerticalSpeed", combined_prompt)
        self.assertNotIn("PRIVATE_SENTINEL", combined_prompt)
        self.assertLess(len(combined_prompt), 45_000)


if __name__ == "__main__":
    unittest.main()

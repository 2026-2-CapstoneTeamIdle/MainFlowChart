from __future__ import annotations

import json
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
    checklist_matches_approved_features,
    UnityChecklistTestGenerator,
    _validate_test_method_source,
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


def _logic_analysis_with_thirty_items() -> LogicAnalysis:
    logic = _logic_analysis()
    logic["features"] = [
        {**feature, "acceptance_items": [f"규칙 {index}" for index in range(21)]}
        for feature in logic["features"]
    ]
    return logic


class DynamicFeatureChecklistTest(unittest.TestCase):
    def test_unity_method_accepts_equivalent_enumerator_and_attribute_layout(self) -> None:
        source = (
            "[Timeout(1000)]\n"
            "[UnityTest]\n"
            "public System.Collections.IEnumerator DFC001_01_Check() "
            "{ yield return null; Assert.That(true); }"
        )

        normalized = _validate_test_method_source(source, "DFC001_01")

        self.assertIn("[UnityTest]\npublic IEnumerator DFC001_01_Check()", normalized)
        self.assertIn("[Timeout(1000)]", normalized)

    def test_unity_method_adds_missing_attribute_only_for_expected_method(self) -> None:
        source = "public IEnumerator DFC001_01_Check() { yield return null; Assert.That(true); }"
        self.assertTrue(
            _validate_test_method_source(source, "DFC001_01").startswith("[UnityTest]\n")
        )
        with self.assertRaisesRegex(ValueError, "must implement only"):
            _validate_test_method_source(source, "DFC001_02")

    def test_unity_method_rejects_regular_nunit_test_attribute(self) -> None:
        with self.assertRaisesRegex(ValueError, "must use \\[UnityTest\\]"):
            _validate_test_method_source(
                "[Test] public IEnumerator DFC001_01_Check() { yield return null; }",
                "DFC001_01",
            )

    def test_test_body_receives_host_owned_unity_method(self) -> None:
        source = _validate_test_method_source("yield return null; Assert.That(true);", "DFC001_01")
        self.assertIn("[UnityTest]\npublic IEnumerator DFC001_01_Check()", source)
        self.assertIn("Assert.That(true)", source)
        with self.assertRaisesRegex(ValueError, "requires an executable assertion"):
            _validate_test_method_source("yield return null;", "DFC001_01")

    def test_partial_and_stale_checklists_regenerate_only_affected_feature(self) -> None:
        class CriterionClient:
            def __init__(self) -> None:
                self.calls: list[str] = []

            def generate_json(self, prompt, _schema):
                target = json.loads(prompt.split("INPUT=", 1)[1])["target_feature"]["feature_id"]
                self.calls.append(target)
                return {
                    "criteria": [
                        {
                            "feature_ids": [target],
                            "title": f"{target} rule {index}",
                            "category": "runtime",
                            "setup": f"Setup {index}",
                            "action": f"Action {index}",
                            "expected": f"Expected {index}",
                            "evidence": f"Evidence {index}",
                        }
                        for index in range(10)
                    ]
                }

        logic = _logic_analysis()
        first_only = {**logic, "features": logic["features"][:1]}
        client = CriterionClient()
        generator = DynamicFeatureChecklistGenerator(client, "test")
        partial = generator.generate(
            project_id="project", logic_analysis=first_only, source_root=Path("missing")
        )
        assert len(client.calls) == 1
        completed = generator.generate(
            project_id="project",
            logic_analysis=logic,
            source_root=Path("missing"),
            existing=partial,
        )
        self.assertEqual(client.calls, ["feature-01", "requirement-dependency-01"])
        self.assertTrue(checklist_matches_approved_features(completed, logic, "project"))
        changed = {
            **logic,
            "features": [
                {**logic["features"][0], "description": "Changed jump behavior"},
                logic["features"][1],
            ],
        }
        regenerated = generator.generate(
            project_id="project",
            logic_analysis=changed,
            source_root=Path("missing"),
            existing=completed,
        )
        self.assertEqual(client.calls[-1], "feature-01")
        self.assertTrue(checklist_matches_approved_features(regenerated, changed, "project"))

    def test_missing_acceptance_items_uses_ten_checks_per_feature(self) -> None:
        criteria = [
            {
                "feature_ids": ["feature-01", "requirement-dependency-01"],
                "title": f"기본 점프 검증 {index}",
                "category": "runtime",
                "setup": "플레이어와 지면을 생성한다.",
                "action": "점프 입력을 보낸다.",
                "expected": "플레이어가 상승한다.",
                "evidence": "위치 전후 비교",
            }
            for index in range(1, 11)
        ]
        client = FakeStructuredClient({"criteria": criteria})
        checklist = DynamicFeatureChecklistGenerator(client, "test").generate(
            project_id="20261122_01",
            logic_analysis=_logic_analysis(),
            source_root=Path("missing"),
        )
        self.assertEqual(len(client.prompts), 2)
        self.assertEqual(len(checklist.feature_checklists), 2)
        self.assertEqual(len(checklist.criteria), 20)
        self.assertTrue(all(len(item.criteria) == 10 for item in checklist.feature_checklists))

    def test_duplicate_batch_is_regenerated_without_losing_valid_items(self) -> None:
        logic = _logic_analysis()
        logic["features"] = [{**logic["features"][0], "acceptance_items": ["점프가 동작한다."]}]
        valid = [
            {
                "feature_ids": ["feature-01"],
                "title": f"점프 검증 {index}",
                "category": "runtime",
                "setup": "플레이어와 지면을 생성한다.",
                "action": "점프 입력을 보낸다.",
                "expected": "플레이어가 상승한다.",
                "evidence": "위치 전후 비교",
            }
            for index in range(1, 11)
        ]

        class RetryClient:
            prompts: list[str] = []

            def generate_json(self, prompt, _schema):
                self.prompts.append(prompt)
                return {"criteria": [valid[0]] * 10 if len(self.prompts) == 1 else valid}

        client = RetryClient()
        checklist = DynamicFeatureChecklistGenerator(client, "test").generate(
            project_id="20261120_03", logic_analysis=logic, source_root=Path("missing")
        )
        self.assertEqual(len(client.prompts), 2)
        self.assertIn("previous batch was rejected", client.prompts[1])
        self.assertEqual(len(checklist.criteria), 10)
        self.assertEqual(len({item.title for item in checklist.criteria}), 10)

    def test_grouped_feature_generates_one_batch_for_eight_rules(self) -> None:
        logic = _logic_analysis()
        logic["features"] = [
            {
                **logic["features"][0],
                "acceptance_items": [f"점프 규칙 {index}" for index in range(8)],
            }
        ]
        criteria = [
            {
                "feature_ids": ["feature-01"],
                "title": f"점프 검증 {index}",
                "category": "runtime",
                "setup": "플레이어와 지면을 생성한다.",
                "action": "점프 입력을 보낸다.",
                "expected": "플레이어가 상승한다.",
                "evidence": "위치 전후 비교",
            }
            for index in range(1, 11)
        ]
        client = FakeStructuredClient({"criteria": criteria})
        checklist = DynamicFeatureChecklistGenerator(client, "test").generate(
            project_id="20261102_02",
            logic_analysis=logic,
            source_root=Path("missing"),
        )
        self.assertEqual(len(client.prompts), 1)
        self.assertEqual(len(checklist.criteria), 10)
        self.assertIn("점프 규칙 7", client.prompts[0])

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
        test_client = FakeStructuredClient({"methods": methods})
        UnityChecklistTestGenerator(test_client, "test").generate(
            checklist=checklist.feature_checklists[0],
            project_root=Path("missing"),
        )
        self.assertEqual(len(test_client.prompts), 1)
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            persist_generated_checklist(
                checklist,
                workspace_root=workspace,
                project_root=workspace / "game" / "unity_project",
            )
            restored = load_generated_checklist(workspace)
            self.assertIsNotNone(restored)
            self.assertEqual(len(restored.criteria), 10)

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
            logic_analysis=_logic_analysis_with_thirty_items(),
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
            logic_analysis=_logic_analysis_with_thirty_items(),
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
                logic_analysis=_logic_analysis_with_thirty_items(),
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

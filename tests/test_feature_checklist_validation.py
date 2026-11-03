import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from game_pipeline.feature_checklist_validation import (
    ChecklistResult,
    FeatureChecklistRepairAI,
    FeatureChecklistWorkflow,
)


class FeatureChecklistValidationTest(unittest.TestCase):
    def test_retry_limit_is_capped_at_ten(self) -> None:
        with self.assertRaises(ValueError):
            FeatureChecklistWorkflow(
                unity_editor="Unity.exe",
                timeout_seconds=30,
                max_retries=11,
            )

    def test_nunit_report_maps_each_feature_result(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            report = Path(temporary_directory) / "results.xml"
            report.write_text(
                """<?xml version="1.0" encoding="utf-8"?>
<test-run>
  <test-suite>
    <test-case fullname="Tests.FC02_EightDirectionMovement" result="Passed" />
    <test-case fullname="Tests.FC05_Jump" result="Failed">
      <failure><message>jump velocity was zero</message></failure>
    </test-case>
    <test-case fullname="Tests.FC09_TowerPlacement" result="Skipped" label="Ignored">
      <reason><message>not requested</message></reason>
    </test-case>
    <test-case fullname="Tests.FC13_TowerUpgrade" result="Passed" />
  </test-suite>
</test-run>
""",
                encoding="utf-8",
            )

            results = FeatureChecklistWorkflow._parse_nunit(report)

        self.assertEqual([item.feature_id for item in results], ["FC02", "FC05", "FC09", "FC13"])
        self.assertEqual(
            [item.status for item in results], ["passed", "failed", "skipped", "passed"]
        )
        self.assertEqual(results[1].message, "jump velocity was zero")

    def test_original_docx_is_preserved_and_checked_copy_is_annotated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source_root = root / "sources"
            source_root.mkdir()
            source = source_root / "[Validator Checklist] 05_점프.docx"
            original_document = (
                '<?xml version="1.0" encoding="utf-8"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/'
                'wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>원본</w:t>'
                "</w:r></w:p><w:sectPr /></w:body></w:document>"
            ).encode("utf-8")
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr("word/document.xml", original_document)
            before = source.read_bytes()
            workspace = root / "workspace"
            workspace.mkdir()
            history = [
                {
                    "attempt": 0,
                    "results": [
                        ChecklistResult(
                            "FC05",
                            "점프",
                            "failed",
                            "upward velocity missing",
                            "Tests.FC05_Jump",
                        ).__dict__
                    ],
                }
            ]

            FeatureChecklistWorkflow._copy_checklist_sources(source_root, workspace)
            FeatureChecklistWorkflow._write_records(workspace, history, source_root)

            self.assertEqual(source.read_bytes(), before)
            copied = workspace / "validation/feature_checklists/original" / source.name
            checked = (
                workspace
                / "validation/feature_checklists/checked"
                / "[Validator Checklist] 05_점프_체크본.docx"
            )
            self.assertEqual(copied.read_bytes(), before)
            self.assertTrue(checked.is_file())
            with zipfile.ZipFile(checked) as archive:
                checked_xml = archive.read("word/document.xml").decode("utf-8")
            self.assertIn("upward velocity missing", checked_xml)
            self.assertTrue((workspace / "Feature검증기록.md").is_file())

    def test_ai_plan_rejects_host_owned_test_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            protected = root / "Assets/Tests/PlayMode/FeatureChecklistTests.cs"
            protected.parent.mkdir(parents=True)
            protected.write_text("host test", encoding="utf-8")
            ai = object.__new__(FeatureChecklistRepairAI)
            ai.max_files = 8
            payload = json.dumps(
                {
                    "target_files": ["Assets/Tests/PlayMode/FeatureChecklistTests.cs"],
                    "rationale": "cheat",
                    "required_changes": ["weaken test"],
                }
            )

            with self.assertRaises(ValueError):
                ai._parse_plan(payload, root)

    def test_inferred_feature_checklist_is_preserved_as_original_and_checked_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source_root = root / "docs"
            source_root.mkdir()
            workspace = root / "workspace"
            workspace.mkdir()
            feature = {
                "feature_id": "requirement-dependency-01",
                "name": "접촉 피해 연결",
                "description": "적 접촉이 플레이어 체력을 감소시킨다.",
                "source_text": "사용자 요구 의존 기능 추론",
                "origin": "requirement_dependency",
                "rationale": "생존 게임의 접촉 결과가 필요하다.",
                "acceptance_criteria": "접촉 전후 플레이어 체력이 감소한다.",
                "supports_feature_ids": ["feature-01"],
                "checklist": {
                    "preconditions": ["플레이어와 적의 Collider2D가 활성화된다."],
                    "steps": ["적을 플레이어와 접촉시킨다."],
                    "expected_results": ["플레이어 체력이 감소한다."],
                    "failure_signals": ["접촉 후 체력이 변하지 않는다."],
                },
            }

            FeatureChecklistWorkflow._copy_checklist_sources(
                source_root,
                workspace,
                feature_requirements=[feature],  # type: ignore[list-item]
            )
            FeatureChecklistWorkflow._write_records(workspace, [], source_root)

            originals = workspace / "validation/feature_checklists/original"
            generated = next(originals.glob("[[]Generated Validator Checklist[]]*.md"))
            checked = (
                workspace / "validation/feature_checklists/checked" / f"{generated.stem}_체크본.md"
            )
            self.assertIn("플레이어 체력이 감소", generated.read_text(encoding="utf-8"))
            self.assertTrue(checked.is_file())
            self.assertIn("상태: pending", checked.read_text(encoding="utf-8"))

    def test_dynamic_generation_failure_falls_back_to_static_unity_tests(self) -> None:
        class FailingGenerator:
            def generate(self, **_kwargs):
                raise RuntimeError("simulated local checklist truncation")

        logic_analysis = {
            "contract_version": "1.0.0",
            "logic_analysis_id": "logic-test",
            "genre": "플랫포머",
            "viewpoint": "사이드뷰",
            "mood_style": "Fantasy",
            "core_loop": "목표에 도달한다.",
            "features": [
                {
                    "feature_id": "feature-01",
                    "name": "점프",
                    "description": "플레이어가 점프한다.",
                    "source_text": "점프 게임",
                }
            ],
            "criteria": [],
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            workspace = root / "workspace"
            project = workspace / "game/unity_project"
            project.mkdir(parents=True)
            workflow = FeatureChecklistWorkflow(
                unity_editor="Unity.exe",
                timeout_seconds=30,
                max_retries=0,
                checklist_generator_factory=FailingGenerator,
            )
            static_result = ChecklistResult("FC05", "점프", "passed", "Passed", "Tests.FC05_Jump")
            with patch.object(workflow, "_run_tests", return_value=([static_result], "log")):
                outcome = workflow.run(
                    project_root=project,
                    workspace_root=workspace,
                    source_root=root / "docs",
                    compile_validation=lambda _root: None,
                    project_id="test-project",
                    logic_analysis=logic_analysis,  # type: ignore[arg-type]
                )

            self.assertEqual(outcome.status, "passed")
            self.assertEqual(outcome.results[0].feature_id, "DYNAMIC_CHECKLIST")
            self.assertEqual(outcome.results[0].status, "skipped")
            self.assertIn("static", outcome.log.lower())
            records = json.loads(
                (workspace / "validation/feature_checklists/checked/results.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(records["attempts"][0]["checklist_source"], "static_fallback")


if __name__ == "__main__":
    unittest.main()

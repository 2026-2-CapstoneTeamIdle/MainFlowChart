import json
import tempfile
import unittest
import zipfile
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()

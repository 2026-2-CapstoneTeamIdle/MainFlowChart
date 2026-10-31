from __future__ import annotations

import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from game_pipeline.feature_checklist_validation import RepairPlan
from game_pipeline.visual_validation import (
    MAX_VISUAL_ATTEMPTS,
    VisualRepairOutcome,
    VisualValidationWorkflow,
    VisualVLMReviewer,
    load_visual_checklist,
    visual_attempt_limit,
    visual_validation_enabled,
)
from mainflow.contracts import CONTRACT_VERSION
from mainflow.nodes.visual_validation import RunNodeLLMVisualTargetGenerator
from MCP import ImageRunResult
from MCP.llm_types import LLMProviderResponse


class _Target:
    def generate(self, request, logic):
        return b"target-png"


class _Capture:
    def capture(self, project_root):
        return b"current-png", "capture log"


class _Reviewer:
    def __init__(self, statuses: list[str]) -> None:
        self.statuses = statuses

    def review(self, **kwargs):
        status = self.statuses.pop(0)
        return (
            {
                "status": status,
                "score": 90 if status == "passed" else 50,
                "summary": status,
                "checklist_results": [],
                "findings": []
                if status == "passed"
                else [
                    {
                        "severity": "error",
                        "criterion_id": "VC01",
                        "message": "layout mismatch",
                        "recommendation": "move player",
                        "suggested_files": ["Assets/GameTemplate/Generated/layout.json"],
                    }
                ],
            },
            "qwen3-vl-test",
        )


class _Repair:
    def repair(self, project_root, failures, compile_log):
        path = project_root / "Assets/GameTemplate/Generated/layout.json"
        path.write_text('{"x": 2}', encoding="utf-8")
        return RepairPlan(("Assets/GameTemplate/Generated/layout.json",), "layout", ("move",))


class VisualValidationTest(unittest.TestCase):
    def test_vlm_retries_incomplete_checklist_response(self) -> None:
        checklist_ids = tuple(f"VC{index:02d}" for index in range(1, 11))
        responses = []
        for count in (9, 10):
            responses.append(
                json.dumps(
                    {
                        "status": "passed",
                        "score": 90,
                        "summary": "ok",
                        "results": [
                            {"id": criterion_id, "s": "passed", "m": "visible"}
                            for criterion_id in checklist_ids[:count]
                        ],
                        "findings": [],
                    }
                )
            )

        class Provider:
            async def complete(self, *args, **kwargs):
                return LLMProviderResponse(text=responses.pop(0))

            async def aclose(self):
                return None

        with (
            patch(
                "game_pipeline.visual_validation.create_llm_provider",
                return_value=Provider(),
            ),
            patch.dict(
                "os.environ",
                {
                    "LLM_VISUAL_VALIDATION_PROVIDER": "local",
                    "LLM_VISUAL_VALIDATION_RESPONSE_ATTEMPTS": "2",
                },
                clear=True,
            ),
        ):
            result, _ = VisualVLMReviewer().review(
                target=b"target",
                current=b"current",
                checklist="visual checklist",
                checklist_ids=checklist_ids,
                request={
                    "contract_version": CONTRACT_VERSION,
                    "image_style": "Pixel Art",
                    "mood_style": "Fantasy",
                    "genre": "플랫포머",
                    "viewpoint": "사이드뷰",
                    "condition": "보석을 모은다.",
                    "custom_image": None,
                },
                inventory=[],
            )

        self.assertEqual(result["status"], "passed")
        self.assertEqual(responses, [])

    def test_target_generator_uses_validation_scoped_node_runner_image(self) -> None:
        reference = {
            "contract_version": CONTRACT_VERSION,
            "artifact_id": "validation-target",
            "project_id": "20261031_01",
            "category": "validation",
            "relative_path": "validation/visual_target_source_01.png",
            "media_type": "image/png",
            "size_bytes": 10,
            "sha256": "0" * 64,
            "created_at": "now",
            "producer": "visual_validation:run_node_llm",
        }
        manager = MagicMock()
        manager.read_bytes.return_value = b"target-png"
        llm_result = ImageRunResult(
            artifacts=(reference,),
            provider="local",
            model="sd-turbo",
            prompt="target",
            size="512x288",
        )
        request = {
            "contract_version": CONTRACT_VERSION,
            "image_style": "Pixel Art",
            "mood_style": "Fantasy",
            "genre": "플랫포머",
            "viewpoint": "사이드뷰",
            "condition": "보석을 모은다.",
            "custom_image": None,
        }
        logic = {
            "contract_version": CONTRACT_VERSION,
            "logic_analysis_id": "logic",
            "genre": "플랫포머",
            "viewpoint": "사이드뷰",
            "mood_style": "Fantasy",
            "core_loop": "collect",
            "features": [],
            "criteria": [],
        }

        with patch(
            "mainflow.nodes.visual_validation.run_node_llm",
            new=AsyncMock(return_value=llm_result),
        ) as run_node_llm:
            content = RunNodeLLMVisualTargetGenerator(manager).generate(request, logic)

        self.assertEqual(content, b"target-png")
        options = run_node_llm.await_args.kwargs["image_options"]
        self.assertEqual(options.artifact_category, "validation")
        self.assertEqual(run_node_llm.await_args.kwargs["output"], "image")
        manager.read_bytes.assert_called_once_with(reference)

    def test_mode_and_attempt_bounds(self) -> None:
        self.assertTrue(visual_validation_enabled("enabled"))
        self.assertFalse(visual_validation_enabled("off"))
        self.assertEqual(visual_attempt_limit("3"), MAX_VISUAL_ATTEMPTS)
        with self.assertRaises(ValueError):
            visual_attempt_limit("4")

    def test_repository_checklist_has_stable_ids(self) -> None:
        checklist = Path(__file__).resolve().parents[1] / "Visual Checklist.md"
        _, ids = load_visual_checklist(checklist)
        self.assertEqual(ids, tuple(f"VC{index:02d}" for index in range(1, 11)))

    def test_vlm_cannot_pass_with_failed_required_criterion(self) -> None:
        results = [
            {
                "criterion_id": f"VC{index:02d}",
                "status": "failed" if index == 1 else "passed",
                "message": "evidence",
                "evidence": [],
            }
            for index in range(1, 11)
        ]
        with self.assertRaises(ValueError):
            VisualVLMReviewer._validate(
                {
                    "status": "passed",
                    "score": 90,
                    "summary": "invalid pass",
                    "checklist_results": results,
                    "findings": [],
                },
                tuple(f"VC{index:02d}" for index in range(1, 11)),
            )

    def test_compact_vlm_payload_is_expanded_to_contract(self) -> None:
        payload = VisualVLMReviewer._normalize(
            {
                "status": "needs_revision",
                "score": 50,
                "summary": "different",
                "results": [{"id": "VC01", "s": "failed", "m": "layout differs"}],
                "findings": [
                    {
                        "sev": "error",
                        "id": "VC01",
                        "problem": "layout differs",
                        "fix": "move player",
                        "files": ["Assets/layout.json"],
                    }
                ],
            }
        )
        self.assertEqual(payload["checklist_results"][0]["criterion_id"], "VC01")
        self.assertEqual(payload["findings"][0]["recommendation"], "move player")

    def test_local_vlm_status_aliases_are_normalized(self) -> None:
        payload = VisualVLMReviewer._normalize(
            {
                "status": "failed",
                "score": 10,
                "summary": "different",
                "results": [{"id": "VC01", "s": "unknown", "m": "not visible"}],
                "findings": [
                    {
                        "sev": "critical",
                        "id": "VC01",
                        "problem": "missing",
                        "fix": "add it",
                        "files": [],
                    }
                ],
            }
        )
        self.assertEqual(payload["status"], "needs_revision")
        self.assertEqual(payload["checklist_results"][0]["status"], "unverifiable")
        self.assertEqual(payload["findings"][0]["severity"], "error")

    def test_workflow_repairs_then_passes_and_never_exceeds_three_attempts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "unity_project"
            generated = project / "Assets/GameTemplate/Generated"
            generated.mkdir(parents=True)
            (generated / "layout.json").write_text('{"x": 1}', encoding="utf-8")
            checklist = root / "Visual Checklist.md"
            checklist.write_text("| VC01 | yes | layout | pass |", encoding="utf-8")
            statuses = ["needs_revision", "passed"]
            workflow = VisualValidationWorkflow(
                editor=root / "Unity.exe",
                timeout_seconds=10,
                checklist_path=checklist,
                source_docs=root,
                attempts=3,
                target_generator=_Target(),
                reviewer_factory=lambda: _Reviewer(statuses),
                capture=_Capture(),
                repair_factory=_Repair,
            )
            workflow._hard_validation = lambda *args, **kwargs: VisualRepairOutcome(  # type: ignore[method-assign]
                [], True, True, "ok"
            )
            images = []

            def record(name, content):
                images.append(name)
                return {
                    "contract_version": CONTRACT_VERSION,
                    "artifact_id": name,
                    "project_id": "20261030_01",
                    "category": "validation",
                    "relative_path": name,
                    "media_type": "image/png",
                    "size_bytes": len(content),
                    "sha256": "0" * 64,
                    "created_at": "now",
                    "producer": "test",
                }

            result = workflow.run(
                project_root=project,
                workspace_root=root,
                request={
                    "contract_version": CONTRACT_VERSION,
                    "image_style": "Pixel Art",
                    "mood_style": "Fantasy",
                    "genre": "플랫포머",
                    "viewpoint": "사이드뷰",
                    "condition": "보석을 모은다.",
                    "custom_image": None,
                },
                logic={
                    "contract_version": CONTRACT_VERSION,
                    "logic_analysis_id": "logic",
                    "genre": "플랫포머",
                    "viewpoint": "사이드뷰",
                    "mood_style": "Fantasy",
                    "core_loop": "collect",
                    "features": [],
                    "criteria": [],
                },
                draft={
                    "contract_version": CONTRACT_VERSION,
                    "draft_id": "draft",
                    "status": "generated",
                    "engine": "Unity",
                    "entry_scene": "Assets/Scenes/Bootstrap.unity",
                    "source_artifacts": [],
                    "required_image_asset_ids": [],
                    "required_sound_asset_ids": [],
                    "notes": [],
                },
                record_image=record,
            )
            self.assertEqual(result["status"], "passed")
            self.assertEqual(len(result["attempts"]), 2)
            self.assertEqual(
                result["attempts"][0]["modified_files"],
                ["Assets/GameTemplate/Generated/layout.json"],
            )
            self.assertEqual(
                images,
                [
                    "visual/target.png",
                    "visual/attempt_1.png",
                    "visual/attempt_2.png",
                ],
            )

    def test_invalid_mode_value_is_rejected(self) -> None:
        with patch.dict("os.environ", {}, clear=True), self.assertRaises(ValueError):
            visual_validation_enabled("maybe")


if __name__ == "__main__":
    unittest.main()

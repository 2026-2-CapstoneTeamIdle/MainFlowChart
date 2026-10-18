from __future__ import annotations

import unittest

from game_pipeline import (
    GameDevelopmentLoop,
    build_game_logic_design,
    normalize_game_spec,
)


class GameDevelopmentLoopTest(unittest.TestCase):
    def _plan(self):
        design = build_game_logic_design(
            normalize_game_spec("플랫포머", {"mechanics": ["time_rewind"]})
        )
        return design["implementation_tasks"]

    @staticmethod
    def _complete_assembly_prerequisites(loop: GameDevelopmentLoop) -> None:
        plan = loop.snapshot()
        for task in plan["tasks"]:
            if task["status"] == "pending" and task["category"] in {
                "module_reuse",
                "content_configuration",
                "level_assembly",
                "ui_binding",
            }:
                loop.mark_passed(task["task_id"], "deterministic contract check passed")

    def test_plan_contains_one_task_per_unsupported_mechanic(self) -> None:
        plan = self._plan()
        tasks = {task["task_id"]: task for task in plan["tasks"]}

        self.assertIn("generate-time-rewind", tasks)
        self.assertIn(
            "generate-time-rewind",
            tasks["unity-project-generation"]["dependencies"],
        )

    def test_executes_dag_and_records_retry_evidence(self) -> None:
        records: list[tuple[str, dict]] = []
        loop = GameDevelopmentLoop(
            self._plan(),
            record=lambda name, plan: records.append((name, plan)),
        )
        loop.mark_passed("design-review", "seven design documents validated")
        loop.mark_passed("module-selection", "reusable modules selected")
        self._complete_assembly_prerequisites(loop)
        attempts = 0

        def generate_feature() -> str:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise ValueError("invalid generated source")
            return "TimeRewindModule"

        result = loop.run_task(
            "generate-time-rewind",
            generate_feature,
            evidence=lambda class_name: f"compiled {class_name}",
        )
        loop.run_task("unity-project-generation", lambda: "project")
        loop.run_task("project-context-review", lambda: "approved")
        loop.run_task("unity-playmode-validation", lambda: "passed")
        loop.run_task("quality-evaluation", lambda: "score=100")
        loop.run_task("package-project", lambda: b"archive")
        loop.require_complete()

        self.assertEqual(result, "TimeRewindModule")
        feature_task = next(
            task for task in loop.snapshot()["tasks"] if task["task_id"] == "generate-time-rewind"
        )
        self.assertEqual(feature_task["attempts"], 2)
        self.assertEqual(feature_task["status"], "passed")
        self.assertIn("ValueError", feature_task["evidence"][0])
        self.assertEqual(feature_task["evidence"][-1], "compiled TimeRewindModule")
        self.assertTrue(any("retry" in name for name, _ in records))

    def test_blocks_task_until_dependencies_pass(self) -> None:
        loop = GameDevelopmentLoop(self._plan())

        with self.assertRaisesRegex(RuntimeError, "blocked by"):
            loop.run_task("unity-project-generation", lambda: "project")

    def test_marks_terminal_failure_after_attempt_budget(self) -> None:
        loop = GameDevelopmentLoop(self._plan())
        loop.mark_passed("design-review", "validated")
        loop.mark_passed("module-selection", "selected")

        with self.assertRaisesRegex(ValueError, "still invalid"):
            loop.run_task(
                "generate-time-rewind",
                lambda: (_ for _ in ()).throw(ValueError("still invalid")),
            )

        task = next(
            task for task in loop.snapshot()["tasks"] if task["task_id"] == "generate-time-rewind"
        )
        self.assertEqual(task["attempts"], 2)
        self.assertEqual(task["status"], "failed")


if __name__ == "__main__":
    unittest.main()

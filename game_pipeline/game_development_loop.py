"""Stateful, bounded execution of implementation tasks with durable evidence."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from time import monotonic
from typing import TypeVar, cast

from mainflow.contracts import ImplementationTask, ImplementationTaskPlan

ResultT = TypeVar("ResultT")
Recorder = Callable[[str, ImplementationTaskPlan], None]


class GameDevelopmentLoop:
    def __init__(
        self,
        plan: ImplementationTaskPlan,
        *,
        record: Recorder | None = None,
    ) -> None:
        self.plan = deepcopy(plan)
        self._tasks = {task["task_id"]: task for task in self.plan["tasks"]}
        if len(self._tasks) != len(self.plan["tasks"]):
            raise ValueError("Implementation task IDs must be unique")
        self._record = record
        self._started_at = monotonic()
        self._revision = 0
        self._validate_dependencies()
        self._persist("planned")

    def run_task(
        self,
        task_id: str,
        action: Callable[[], ResultT],
        *,
        evidence: Callable[[ResultT], str] | None = None,
    ) -> ResultT:
        task = self._task(task_id)
        self._require_ready(task)
        while task["attempts"] < task["max_attempts"]:
            self._check_time_budget()
            task["attempts"] += 1
            task["status"] = "running"
            task["last_error"] = None
            self._persist(task_id + "-running")
            try:
                result = action()
                self._check_time_budget()
            except Exception as error:
                task["last_error"] = f"{type(error).__name__}: {error}"
                task["evidence"].append(f"attempt {task['attempts']} failed: {task['last_error']}")
                if task["attempts"] >= task["max_attempts"]:
                    task["status"] = "failed"
                    self._persist(task_id + "-failed")
                    raise
                task["status"] = "pending"
                self._persist(task_id + "-retry")
                continue

            task["status"] = "passed"
            task["evidence"].append(
                evidence(result) if evidence is not None else f"attempt {task['attempts']} passed"
            )
            self._persist(task_id + "-passed")
            return result
        raise AssertionError("unreachable")

    def mark_passed(self, task_id: str, evidence: str) -> None:
        task = self._task(task_id)
        self._require_ready(task)
        task["attempts"] += 1
        task["status"] = "passed"
        task["last_error"] = None
        task["evidence"].append(evidence)
        self._persist(task_id + "-passed")

    def require_complete(self) -> None:
        incomplete = [task["task_id"] for task in self.plan["tasks"] if task["status"] != "passed"]
        if incomplete:
            raise RuntimeError("Implementation tasks are incomplete: " + ", ".join(incomplete))

    def snapshot(self) -> ImplementationTaskPlan:
        return deepcopy(self.plan)

    def _task(self, task_id: str) -> ImplementationTask:
        try:
            return self._tasks[task_id]
        except KeyError as error:
            raise KeyError(f"Unknown implementation task: {task_id}") from error

    def _require_ready(self, task: ImplementationTask) -> None:
        if task["status"] == "passed":
            raise RuntimeError(f"Implementation task already passed: {task['task_id']}")
        blocked = [
            dependency
            for dependency in task["dependencies"]
            if self._task(dependency)["status"] != "passed"
        ]
        if blocked:
            raise RuntimeError(
                f"Implementation task {task['task_id']} is blocked by: {', '.join(blocked)}"
            )

    def _check_time_budget(self) -> None:
        if monotonic() - self._started_at > self.plan["time_budget_seconds"]:
            raise TimeoutError("Game development time budget was exhausted")

    def _validate_dependencies(self) -> None:
        for task in self.plan["tasks"]:
            for dependency in task["dependencies"]:
                if dependency not in self._tasks:
                    raise ValueError(
                        f"Implementation task {task['task_id']} has unknown dependency {dependency}"
                    )
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(task_id: str) -> None:
            if task_id in visiting:
                raise ValueError("Implementation task dependencies contain a cycle")
            if task_id in visited:
                return
            visiting.add(task_id)
            for dependency in self._task(task_id)["dependencies"]:
                visit(dependency)
            visiting.remove(task_id)
            visited.add(task_id)

        for task_id in self._tasks:
            visit(task_id)

    def _persist(self, event: str) -> None:
        if self._record is None:
            return
        self._revision += 1
        safe_event = "".join(character if character.isalnum() else "_" for character in event)
        self._record(
            f"{self._revision:03d}_{safe_event}", cast(ImplementationTaskPlan, self.snapshot())
        )

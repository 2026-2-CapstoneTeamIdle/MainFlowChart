"""Run the MainFlowChart LangGraph workflow in the background for the local web UI.

Runs execute one at a time in submission order. Each run streams per-node
updates from ``graph.stream(..., stream_mode="updates")`` so the browser can
show progress while the graph is still running. Agent nodes and graph edges
are used exactly as ``mainflow.langgraph_game_flow_skeleton.build_graph``
defines them.
"""

from __future__ import annotations

import threading
import time
import traceback
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from mainflow.ArtifactManager import ArtifactManager

GraphFactory = Callable[[], Any]

# State keys whose artifacts summarize the outcome, mirroring mainflow.run_flow.
RESULT_KEYS = {
    "game_validation": "game_validation_result",
    "image_generation": "image_draft",
    "sound_generation": "sound_draft",
    "final_validation": "final_validation_result",
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def default_graph_factory() -> Any:
    from mainflow.langgraph_game_flow_skeleton import build_graph

    return build_graph()


@dataclass
class NodeEvent:
    node: str
    finished_at: str
    elapsed_ms: float
    output_keys: list[str]


@dataclass
class WorkflowRun:
    run_id: str
    request: dict[str, Any]
    status: str = "queued"
    created_at: str = field(default_factory=_now)
    started_at: str | None = None
    finished_at: str | None = None
    project_id: str | None = None
    events: list[NodeEvent] = field(default_factory=list)
    results: dict[str, Any] = field(default_factory=dict)
    outcome: str | None = None
    error: str | None = None


class WorkflowRunner:
    """Thread-safe run registry with a single background worker."""

    def __init__(self, graph_factory: GraphFactory = default_graph_factory) -> None:
        self._graph_factory = graph_factory
        self._runs: dict[str, WorkflowRun] = {}
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="workflow")
        self._node_names: list[str] | None = None

    def node_names(self) -> list[str]:
        """Graph node order; building the graph also proves the workflow imports."""
        if self._node_names is None:
            graph = self._graph_factory().get_graph()
            self._node_names = [name for name in graph.nodes if not name.startswith("__")]
        return list(self._node_names)

    def submit(self, initial_state: dict[str, Any], public_request: dict[str, Any]) -> WorkflowRun:
        run = WorkflowRun(run_id=f"run-{uuid.uuid4().hex[:12]}", request=public_request)
        with self._lock:
            self._runs[run.run_id] = run
        self._executor.submit(self._execute, run.run_id, initial_state)
        return self.get(run.run_id)  # type: ignore[return-value]

    def get(self, run_id: str) -> WorkflowRun | None:
        with self._lock:
            run = self._runs.get(run_id)
            return deepcopy(run) if run else None

    def list(self) -> list[WorkflowRun]:
        with self._lock:
            runs = [deepcopy(run) for run in self._runs.values()]
        return sorted(runs, key=lambda run: run.created_at, reverse=True)

    def busy(self) -> bool:
        with self._lock:
            return any(run.status in ("queued", "running") for run in self._runs.values())

    def _update(self, run_id: str, **changes: Any) -> None:
        with self._lock:
            run = self._runs[run_id]
            for key, value in changes.items():
                setattr(run, key, value)

    def _execute(self, run_id: str, initial_state: dict[str, Any]) -> None:
        self._update(run_id, status="running", started_at=_now())
        state: dict[str, Any] = dict(initial_state)
        clock = time.perf_counter()
        try:
            graph = self._graph_factory()
            for chunk in graph.stream(initial_state, stream_mode="updates"):
                for node, update in chunk.items():
                    now = time.perf_counter()
                    update = update or {}
                    state.update(update)
                    event = NodeEvent(node, _now(), round((now - clock) * 1000, 1), sorted(update))
                    clock = now
                    with self._lock:
                        run = self._runs[run_id]
                        run.events.append(event)
                        if "project_id" in update:
                            run.project_id = update["project_id"]
            results = self._summarize(state)
            game_status = results.get("game_validation", {}).get("status")
            self._update(
                run_id,
                status="succeeded",
                finished_at=_now(),
                results=results,
                outcome="passed" if game_status == "passed" else "game_validation_failed",
            )
        except Exception as error:  # noqa: BLE001 - surfaced to the UI as the run error
            traceback.print_exc()
            self._update(
                run_id,
                status="failed",
                finished_at=_now(),
                error=f"{type(error).__name__}: {error}",
            )

    @staticmethod
    def _summarize(state: dict[str, Any]) -> dict[str, Any]:
        manager = ArtifactManager()
        results: dict[str, Any] = {}
        for name, key in RESULT_KEYS.items():
            reference = state.get(key)
            if reference:
                results[name] = manager.read_json(reference)
        return results


def serialize(run: WorkflowRun) -> dict[str, Any]:
    return asdict(run)

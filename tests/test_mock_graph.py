from __future__ import annotations

import json
import tempfile
import threading
import unittest
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter_ns
from typing import Any, Callable, cast

from langgraph.graph import END, START, StateGraph

from ArtifactManager import ArtifactManager
from contracts import (
    ArtifactCategory,
    ArtifactReference,
    UserInputAgentOutput,
    WorkflowState,
)
from tests.mock_nodes import (
    MockRuntime,
    mock_apply_assets_node,
    mock_asset_validation_spec_node,
    mock_design_game_logic_node,
    mock_final_validation_node,
    mock_generate_image_node,
    mock_generate_sound_node,
    mock_initial_validation_spec_node,
    mock_parse_input_node,
    mock_user_input_node,
    mock_validate_game_node,
    mock_validate_image_node,
    mock_validate_sound_node,
)


FIXTURE_DIRECTORY = Path(__file__).parent / "fixtures"
NodeFunction = Callable[[Any, MockRuntime], dict[str, Any]]

NODE_IO: dict[str, tuple[set[str], set[str]]] = {
    "user_input": (set(), {"image_style", "genre", "quality"}),
    "parse_input": (
        {"image_style", "genre", "quality"},
        {"project_id", "parsed_request"},
    ),
    "create_initial_final_validation_spec": (
        {"project_id", "parsed_request"},
        {"initial_final_validation_spec"},
    ),
    "generate_image": (
        {"project_id", "parsed_request", "initial_final_validation_spec"},
        {"image_draft"},
    ),
    "design_game_logic": (
        {"project_id", "parsed_request", "initial_final_validation_spec"},
        {"game_logic_draft"},
    ),
    "generate_sound": (
        {"project_id", "parsed_request", "initial_final_validation_spec"},
        {"sound_draft"},
    ),
    "validate_game": (
        {
            "project_id",
            "parsed_request",
            "initial_final_validation_spec",
            "game_logic_draft",
        },
        {"game_validation_result"},
    ),
    "create_asset_validation_spec": (
        {"project_id", "parsed_request", "game_validation_result"},
        {"asset_validation_spec"},
    ),
    "validate_image": (
        {"project_id", "parsed_request", "image_draft", "asset_validation_spec"},
        {"image_validation_result"},
    ),
    "validate_sound": (
        {"project_id", "parsed_request", "sound_draft", "asset_validation_spec"},
        {"sound_validation_result"},
    ),
    "apply_assets_to_game": (
        {
            "project_id",
            "game_logic_draft",
            "image_draft",
            "sound_draft",
            "image_validation_result",
            "sound_validation_result",
        },
        {"integrated_game"},
    ),
    "final_validation": (
        {"project_id", "initial_final_validation_spec", "integrated_game"},
        {"final_validation_result"},
    ),
}


@dataclass(frozen=True)
class NodeMeasurement:
    node: str
    elapsed_ms: float
    started_ms: float
    ended_ms: float
    thread: str
    input_keys: list[str]
    output_keys: list[str]


@dataclass(frozen=True)
class NodeExecution:
    output: dict[str, Any]
    measurement: NodeMeasurement


def _load_json(name: str) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads((FIXTURE_DIRECTORY / name).read_text(encoding="utf-8")),
    )


def _run_node(
    node_name: str,
    function: NodeFunction,
    state: dict[str, Any],
    runtime: MockRuntime,
    flow_started_ns: int,
) -> NodeExecution:
    required_inputs, expected_outputs = NODE_IO[node_name]
    missing_inputs = required_inputs - state.keys()
    if missing_inputs:
        raise AssertionError(f"{node_name} missing inputs: {sorted(missing_inputs)}")

    started_ns = perf_counter_ns()
    output = function(state, runtime)
    ended_ns = perf_counter_ns()
    if set(output) != expected_outputs:
        raise AssertionError(f"{node_name} outputs {sorted(output)} != {sorted(expected_outputs)}")

    measurement = NodeMeasurement(
        node=node_name,
        elapsed_ms=(ended_ns - started_ns) / 1_000_000,
        started_ms=(started_ns - flow_started_ns) / 1_000_000,
        ended_ms=(ended_ns - flow_started_ns) / 1_000_000,
        thread=threading.current_thread().name,
        input_keys=sorted(required_inputs),
        output_keys=sorted(expected_outputs),
    )
    return NodeExecution(output=output, measurement=measurement)


def _parallel_span(
    measurements: dict[str, NodeMeasurement],
    node_names: list[str],
) -> float:
    selected = [measurements[name] for name in node_names]
    return max(item.ended_ms for item in selected) - min(item.started_ms for item in selected)


def run_mock_graph(runtime: MockRuntime) -> tuple[dict[str, Any], dict[str, Any]]:
    """Execute the production graph topology with deterministic mock nodes."""

    flow_started_ns = perf_counter_ns()
    state: dict[str, Any] = {}
    measurements: dict[str, NodeMeasurement] = {}

    def execute(
        node_name: str,
        function: NodeFunction,
        input_state: dict[str, Any],
    ) -> NodeExecution:
        execution = _run_node(
            node_name,
            function,
            input_state,
            runtime,
            flow_started_ns,
        )
        measurements[node_name] = execution.measurement
        return execution

    for name, function in [
        ("user_input", mock_user_input_node),
        ("parse_input", mock_parse_input_node),
        (
            "create_initial_final_validation_spec",
            mock_initial_validation_spec_node,
        ),
    ]:
        state.update(execute(name, function, dict(state)).output)

    with ThreadPoolExecutor(
        max_workers=3,
        thread_name_prefix="mock-generation",
    ) as executor:
        generation_futures: dict[str, Future[NodeExecution]] = {
            "generate_image": executor.submit(
                execute,
                "generate_image",
                mock_generate_image_node,
                dict(state),
            ),
            "design_game_logic": executor.submit(
                execute,
                "design_game_logic",
                mock_design_game_logic_node,
                dict(state),
            ),
            "generate_sound": executor.submit(
                execute,
                "generate_sound",
                mock_generate_sound_node,
                dict(state),
            ),
        }

        game_execution = generation_futures["design_game_logic"].result()
        state.update(game_execution.output)
        state.update(execute("validate_game", mock_validate_game_node, dict(state)).output)
        state.update(
            execute(
                "create_asset_validation_spec",
                mock_asset_validation_spec_node,
                dict(state),
            ).output
        )
        state.update(generation_futures["generate_image"].result().output)
        state.update(generation_futures["generate_sound"].result().output)

    with ThreadPoolExecutor(
        max_workers=2,
        thread_name_prefix="mock-validation",
    ) as executor:
        validation_futures = [
            executor.submit(
                execute,
                "validate_image",
                mock_validate_image_node,
                dict(state),
            ),
            executor.submit(
                execute,
                "validate_sound",
                mock_validate_sound_node,
                dict(state),
            ),
        ]
        for future in validation_futures:
            state.update(future.result().output)

    state.update(execute("apply_assets_to_game", mock_apply_assets_node, dict(state)).output)
    state.update(execute("final_validation", mock_final_validation_node, dict(state)).output)

    workflow_wall_ms = (perf_counter_ns() - flow_started_ns) / 1_000_000
    sequential_sum_ms = sum(item.elapsed_ms for item in measurements.values())
    generation_nodes = ["generate_image", "design_game_logic", "generate_sound"]
    validation_nodes = ["validate_image", "validate_sound"]
    metrics = {
        "workflow_wall_ms": workflow_wall_ms,
        "sequential_node_sum_ms": sequential_sum_ms,
        "estimated_parallel_speedup": sequential_sum_ms / workflow_wall_ms,
        "generation_parallel_span_ms": _parallel_span(measurements, generation_nodes),
        "generation_sequential_sum_ms": sum(
            measurements[name].elapsed_ms for name in generation_nodes
        ),
        "asset_validation_parallel_span_ms": _parallel_span(measurements, validation_nodes),
        "asset_validation_sequential_sum_ms": sum(
            measurements[name].elapsed_ms for name in validation_nodes
        ),
        "nodes": [
            asdict(item) for item in sorted(measurements.values(), key=lambda item: item.started_ms)
        ],
    }
    return state, metrics


def build_mock_langgraph(runtime: MockRuntime):
    """Compile the production topology with mock Node implementations."""

    graph = StateGraph(WorkflowState)
    graph.add_node("user_input", lambda state: mock_user_input_node(state, runtime))
    graph.add_node("parse_input", lambda state: mock_parse_input_node(state, runtime))
    graph.add_node(
        "create_initial_final_validation_spec",
        lambda state: mock_initial_validation_spec_node(state, runtime),
    )
    graph.add_node(
        "generate_image",
        lambda state: mock_generate_image_node(state, runtime),
    )
    graph.add_node(
        "design_game_logic",
        lambda state: mock_design_game_logic_node(state, runtime),
    )
    graph.add_node(
        "generate_sound",
        lambda state: mock_generate_sound_node(state, runtime),
    )
    graph.add_node(
        "validate_game",
        lambda state: mock_validate_game_node(state, runtime),
    )
    graph.add_node(
        "create_asset_validation_spec",
        lambda state: mock_asset_validation_spec_node(state, runtime),
    )
    graph.add_node(
        "validate_image",
        lambda state: mock_validate_image_node(state, runtime),
    )
    graph.add_node(
        "validate_sound",
        lambda state: mock_validate_sound_node(state, runtime),
    )
    graph.add_node(
        "apply_assets_to_game",
        lambda state: mock_apply_assets_node(state, runtime),
    )
    graph.add_node(
        "final_validation",
        lambda state: mock_final_validation_node(state, runtime),
    )

    graph.add_edge(START, "user_input")
    graph.add_edge("user_input", "parse_input")
    graph.add_edge("parse_input", "create_initial_final_validation_spec")
    graph.add_edge("create_initial_final_validation_spec", "generate_image")
    graph.add_edge("create_initial_final_validation_spec", "design_game_logic")
    graph.add_edge("create_initial_final_validation_spec", "generate_sound")
    graph.add_edge("design_game_logic", "validate_game")
    graph.add_edge("validate_game", "create_asset_validation_spec")
    graph.add_edge(
        ["generate_image", "create_asset_validation_spec"],
        "validate_image",
    )
    graph.add_edge(
        ["generate_sound", "create_asset_validation_spec"],
        "validate_sound",
    )
    graph.add_edge(
        ["validate_image", "validate_sound"],
        "apply_assets_to_game",
    )
    graph.add_edge("apply_assets_to_game", "final_validation")
    graph.add_edge("final_validation", END)
    return graph.compile()


class MockGraphTest(unittest.TestCase):
    def test_real_langgraph_runtime_with_mock_nodes(self) -> None:
        request_fixture = _load_json("mock_request.json")
        timing_fixture = _load_json("mock_timing.json")

        with tempfile.TemporaryDirectory() as temporary_directory:
            manager = ArtifactManager(Path(temporary_directory) / "workspace")
            runtime = MockRuntime(
                manager=manager,
                request=cast(UserInputAgentOutput, request_fixture["input"]),
                delays_ms=cast(dict[str, float], timing_fixture),
            )
            final_state = build_mock_langgraph(runtime).invoke({})
            final_reference = cast(
                ArtifactReference,
                final_state["final_validation_result"],
            )
            final_result = manager.read_json(final_reference)
            self.assertEqual(final_result["status"], "passed")
            self.assertEqual(
                len(manager.list_artifacts(final_state["project_id"])),
                request_fixture["expected"]["artifact_count"],
            )

    def test_contracts_file_exchange_results_and_parallelism(self) -> None:
        request_fixture = _load_json("mock_request.json")
        timing_fixture = _load_json("mock_timing.json")

        with tempfile.TemporaryDirectory() as temporary_directory:
            manager = ArtifactManager(Path(temporary_directory) / "workspace")
            runtime = MockRuntime(
                manager=manager,
                request=cast(UserInputAgentOutput, request_fixture["input"]),
                delays_ms=cast(dict[str, float], timing_fixture),
            )
            state, metrics = run_mock_graph(runtime)

            project_id = cast(str, state["project_id"])
            final_reference = cast(
                ArtifactReference,
                state["final_validation_result"],
            )
            final_result = manager.read_json(final_reference)
            expected = request_fixture["expected"]
            self.assertEqual(final_result["status"], expected["final_status"])
            self.assertTrue(all(check["passed"] for check in final_result["checks"]))

            artifacts = manager.list_artifacts(project_id)
            self.assertEqual(len(artifacts), expected["artifact_count"])
            for reference in artifacts:
                self.assertTrue(manager.read_bytes(reference))

            for category, expected_count in expected["category_counts"].items():
                self.assertEqual(
                    len(
                        manager.list_artifacts(
                            project_id,
                            cast(ArtifactCategory, category),
                        )
                    ),
                    expected_count,
                )

            node_metrics = {
                item["node"]: item for item in cast(list[dict[str, Any]], metrics["nodes"])
            }
            generation_threads = {
                node_metrics[name]["thread"]
                for name in ["generate_image", "design_game_logic", "generate_sound"]
            }
            validation_threads = {
                node_metrics[name]["thread"] for name in ["validate_image", "validate_sound"]
            }
            self.assertGreaterEqual(len(generation_threads), 2)
            self.assertEqual(len(validation_threads), 2)
            self.assertLess(
                metrics["generation_parallel_span_ms"],
                metrics["generation_sequential_sum_ms"] * 0.70,
            )
            self.assertLess(
                metrics["asset_validation_parallel_span_ms"],
                metrics["asset_validation_sequential_sum_ms"] * 0.80,
            )
            self.assertGreater(metrics["estimated_parallel_speedup"], 1.5)

            print("MOCK_GRAPH_METRICS=" + json.dumps(metrics, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()

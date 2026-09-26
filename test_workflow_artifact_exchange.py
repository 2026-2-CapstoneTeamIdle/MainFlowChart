from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path

try:
    import langgraph.graph  # noqa: F401
except ModuleNotFoundError:
    # Node functions do not depend on LangGraph internals.  A tiny import shim
    # lets this integration test run in environments that only have stdlib.
    langgraph_module = types.ModuleType("langgraph")
    graph_module = types.ModuleType("langgraph.graph")
    graph_module.END = "END"
    graph_module.START = "START"
    graph_module.StateGraph = object
    langgraph_module.graph = graph_module
    sys.modules["langgraph"] = langgraph_module
    sys.modules["langgraph.graph"] = graph_module

import langgraph_game_flow_skeleton as workflow
from ArtifactManager import ArtifactManager


class WorkflowArtifactExchangeTest(unittest.TestCase):
    def test_nodes_exchange_real_json_files_by_reference(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            manager = ArtifactManager(Path(temporary_directory) / "workspace")
            original_factory = workflow.ArtifactManager
            workflow.ArtifactManager = lambda: manager  # type: ignore[assignment]
            try:
                state: dict[str, object] = {
                    "image_style": "Pixel Art",
                    "genre": "Action",
                    "quality": "Medium",
                }
                state.update(workflow.parse_input_node(state))  # type: ignore[arg-type]
                state.update(
                    workflow.create_initial_final_validation_spec_node(state)  # type: ignore[arg-type]
                )
                state.update(workflow.generate_image_node(state))  # type: ignore[arg-type]
                state.update(workflow.design_game_logic_node(state))  # type: ignore[arg-type]
                state.update(workflow.generate_sound_node(state))  # type: ignore[arg-type]
                state.update(workflow.validate_game_node(state))  # type: ignore[arg-type]
                state.update(
                    workflow.create_asset_validation_spec_node(state)  # type: ignore[arg-type]
                )
                state.update(workflow.validate_image_node(state))  # type: ignore[arg-type]
                state.update(workflow.validate_sound_node(state))  # type: ignore[arg-type]
                state.update(workflow.apply_assets_to_game_node(state))  # type: ignore[arg-type]
                state.update(workflow.final_validation_node(state))  # type: ignore[arg-type]
            finally:
                workflow.ArtifactManager = original_factory

            project_id = state["project_id"]
            self.assertIsInstance(project_id, str)
            artifacts = manager.list_artifacts(project_id)  # type: ignore[arg-type]
            self.assertEqual(len(artifacts), 11)

            final_reference = state["final_validation_result"]
            final_payload = manager.read_json(final_reference)  # type: ignore[arg-type]
            self.assertEqual(final_payload["contract_version"], "2.0.0")
            self.assertEqual(final_payload["status"], "pending")


if __name__ == "__main__":
    unittest.main()

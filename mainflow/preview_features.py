"""Run the real request-analysis nodes and stop at the web feature approval gate."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import cast

from mainflow.ArtifactManager import ArtifactManager
from mainflow.contracts import LogicAnalysis, WorkflowState
from mainflow.nodes import analysis_node, logic_analysis_node, parse_input_node, user_input_node
from mainflow.run_flow import configure_console_encoding, load_repository_environment, load_request


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Preview analyzed features for LocalWeb approval.")
    parser.add_argument("--request-file", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output-file", type=Path, required=True)
    return parser


def main() -> int:
    load_repository_environment()
    configure_console_encoding()
    arguments = build_parser().parse_args()
    os.environ["MAINFLOW_WORKSPACE"] = str(arguments.workspace.resolve())
    request_arguments = argparse.Namespace(
        request_file=arguments.request_file,
        image_style=None,
        mood_style=None,
        genre=None,
        viewpoint=None,
        condition=None,
        custom_image=None,
    )
    state = cast(WorkflowState, dict(load_request(request_arguments)))
    for node in (user_input_node, parse_input_node, analysis_node, logic_analysis_node):
        state.update(node(state))

    manager = ArtifactManager()
    logic = cast(LogicAnalysis, manager.read_json(state["logic_analysis"]))
    project_root = manager.ensure_project(state["project_id"])
    payload = {
        "project_id": state["project_id"],
        "logic_analysis_path": str(project_root / "data" / "logic_analysis.json"),
        "features": [
            {
                "feature_id": feature["feature_id"],
                "name": feature["name"],
                "description": feature["description"],
                "origin": feature.get("origin", "user"),
                "rationale": feature.get("rationale", ""),
                "acceptance_criteria": feature.get("acceptance_criteria", ""),
            }
            for feature in logic["features"]
        ],
    }
    arguments.output_file.parent.mkdir(parents=True, exist_ok=True)
    arguments.output_file.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"[WEB] Feature preview saved: project_id={state['project_id']}, "
        f"feature_count={len(logic['features'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

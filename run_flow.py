"""Headless command-line entry point for the production LangGraph workflow."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, cast, get_args

from ArtifactManager import ArtifactManager
from contracts import GameGenre, ImageStyle, QualityLevel, WorkflowState
from langgraph_game_flow_skeleton import build_graph


IMAGE_STYLES = cast(tuple[str, ...], get_args(ImageStyle))
GAME_GENRES = cast(tuple[str, ...], get_args(GameGenre))
QUALITY_LEVELS = cast(tuple[str, ...], get_args(QualityLevel))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run MainFlowChart without a desktop GUI.",
    )
    parser.add_argument(
        "--request-file",
        type=Path,
        help="UTF-8 JSON file containing image_style, genre, and quality.",
    )
    parser.add_argument("--image-style", choices=IMAGE_STYLES)
    parser.add_argument("--genre", choices=GAME_GENRES)
    parser.add_argument("--quality", choices=QUALITY_LEVELS)
    parser.add_argument(
        "--workspace",
        type=Path,
        help="Override the workspace directory (default: ./workspace).",
    )
    return parser


def load_request(arguments: argparse.Namespace) -> WorkflowState:
    if arguments.request_file:
        with arguments.request_file.open("r", encoding="utf-8") as file:
            request = json.load(file)
        if not isinstance(request, dict):
            raise ValueError("request file must contain one JSON object")
    else:
        request = {
            "image_style": arguments.image_style,
            "genre": arguments.genre,
            "quality": arguments.quality,
        }

    required = {"image_style", "genre", "quality"}
    missing = required - request.keys()
    if missing or any(request[key] is None for key in required):
        raise ValueError(
            "Provide --request-file or all of --image-style, --genre, --quality"
        )
    if request["image_style"] not in IMAGE_STYLES:
        raise ValueError(f"Unsupported image_style: {request['image_style']}")
    if request["genre"] not in GAME_GENRES:
        raise ValueError(f"Unsupported genre: {request['genre']}")
    if request["quality"] not in QUALITY_LEVELS:
        raise ValueError(f"Unsupported quality: {request['quality']}")
    return cast(WorkflowState, request)


def main() -> int:
    arguments = build_parser().parse_args()
    if arguments.workspace:
        os.environ["MAINFLOW_WORKSPACE"] = str(arguments.workspace.resolve())

    initial_state = load_request(arguments)
    final_state = cast(WorkflowState, build_graph().invoke(initial_state))
    manager = ArtifactManager()
    final_validation = manager.read_json(final_state["final_validation_result"])
    project_root = manager.ensure_project(final_state["project_id"])

    output: dict[str, Any] = {
        "project_id": final_state["project_id"],
        "project_root": str(project_root),
        "final_validation": final_validation,
        "final_state": final_state,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

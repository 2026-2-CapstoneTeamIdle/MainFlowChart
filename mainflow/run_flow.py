"""Headless command-line entry point for the production LangGraph workflow."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, cast, get_args

from mainflow.ArtifactManager import ArtifactManager
from mainflow.contracts import GameGenre, ImageStyle, MoodStyle, Viewpoint, WorkflowState
from mainflow.langgraph_game_flow_skeleton import build_graph

IMAGE_STYLES = cast(tuple[str, ...], get_args(ImageStyle))
GAME_GENRES = cast(tuple[str, ...], get_args(GameGenre))
MOOD_STYLES = cast(tuple[str, ...], get_args(MoodStyle))
VIEWPOINTS = cast(tuple[str, ...], get_args(Viewpoint))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run MainFlowChart without a desktop GUI.",
    )
    parser.add_argument(
        "--request-file",
        type=Path,
        help="UTF-8 JSON file containing image_style, mood_style, genre, viewpoint, and condition.",
    )
    parser.add_argument("--image-style", choices=IMAGE_STYLES)
    parser.add_argument("--mood-style", choices=MOOD_STYLES)
    parser.add_argument("--genre", choices=GAME_GENRES)
    parser.add_argument("--viewpoint", choices=VIEWPOINTS)
    parser.add_argument("--condition")
    parser.add_argument(
        "--custom-image",
        type=Path,
        help="PNG/JPG reference required when --image-style Custom is selected.",
    )
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
            "mood_style": arguments.mood_style,
            "genre": arguments.genre,
            "viewpoint": arguments.viewpoint,
            "condition": arguments.condition,
        }
        if arguments.custom_image:
            request["custom_image_path"] = str(arguments.custom_image.resolve())

    required = {"image_style", "mood_style", "genre", "viewpoint", "condition"}
    missing = required - request.keys()
    if missing or any(request[key] is None for key in required):
        raise ValueError(
            "Provide --request-file or all of --image-style, --mood-style, --genre, "
            "--viewpoint, --condition"
        )
    if request["image_style"] not in IMAGE_STYLES:
        raise ValueError(f"Unsupported image_style: {request['image_style']}")
    if request["genre"] not in GAME_GENRES:
        raise ValueError(f"Unsupported genre: {request['genre']}")
    if request["mood_style"] not in MOOD_STYLES:
        raise ValueError(f"Unsupported mood_style: {request['mood_style']}")
    if request["viewpoint"] not in VIEWPOINTS:
        raise ValueError(f"Unsupported viewpoint: {request['viewpoint']}")
    if not isinstance(request["condition"], str) or not request["condition"].strip():
        raise ValueError("condition must be one non-empty sentence")
    if request["image_style"] == "Custom":
        custom_image = request.get("custom_image_path")
        if not custom_image:
            raise ValueError("Custom image style requires custom_image_path")
        custom_path = Path(custom_image)
        if not custom_path.is_file() or custom_path.suffix.lower() not in {
            ".png",
            ".jpg",
            ".jpeg",
        }:
            raise ValueError("custom_image_path must point to a PNG or JPG file")
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

"""Headless command-line entry point for the production LangGraph workflow."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, cast, get_args

from mainflow.ArtifactManager import ArtifactManager
from mainflow.contracts import GameGenre, ImageStyle, MoodStyle, Viewpoint, WorkflowState
from mainflow.langgraph_game_flow_skeleton import build_graph

IMAGE_STYLES = cast(tuple[str, ...], get_args(ImageStyle))
GAME_GENRES = cast(tuple[str, ...], get_args(GameGenre))
MOOD_STYLES = cast(tuple[str, ...], get_args(MoodStyle))
VIEWPOINTS = cast(tuple[str, ...], get_args(Viewpoint))


def configure_console_encoding() -> None:
    """Keep CLI output Unicode-safe on Windows terminals that default to CP949."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="backslashreplace")


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
    visual_mode = parser.add_mutually_exclusive_group()
    visual_mode.add_argument(
        "--visual-validation",
        dest="visual_validation",
        action="store_true",
        help="Enable Unity screenshot, VLM comparison, and bounded visual repair.",
    )
    visual_mode.add_argument(
        "--skip-visual-validation",
        dest="visual_validation",
        action="store_false",
        help="Skip screenshot/VLM validation even when the environment enables it.",
    )
    parser.set_defaults(visual_validation=None)
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
    configure_console_encoding()
    arguments = build_parser().parse_args()
    if arguments.workspace:
        os.environ["MAINFLOW_WORKSPACE"] = str(arguments.workspace.resolve())
    if arguments.visual_validation is not None:
        os.environ["MAINFLOW_VISUAL_VALIDATION"] = "1" if arguments.visual_validation else "0"

    initial_state = load_request(arguments)
    final_state = cast(WorkflowState, build_graph().invoke(initial_state))
    manager = ArtifactManager()
    game_validation = manager.read_json(final_state["game_validation_result"])
    image_generation = manager.read_json(final_state["image_draft"])
    sound_generation = manager.read_json(final_state["sound_draft"])
    final_validation = manager.read_json(final_state["final_validation_result"])
    visual_reference = final_state.get("visual_validation_result")
    visual_validation = (
        manager.read_json(visual_reference)
        if visual_reference is not None
        else {
            "mode": "disabled",
            "status": "skipped",
            "summary": "Visual validation result was not emitted by the invoked graph.",
        }
    )
    game_validator_ai = manager.read_json(final_state["game_validator_ai_result"])
    project_root = manager.ensure_project(final_state["project_id"])

    output: dict[str, Any] = {
        "project_id": final_state["project_id"],
        "project_root": str(project_root),
        "game_validation": game_validation,
        "image_generation": image_generation,
        "sound_generation": sound_generation,
        "final_validation": final_validation,
        "visual_validation": visual_validation,
        "game_validator_ai": game_validator_ai,
        "final_state": final_state,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    if final_validation.get("status") != "passed":
        print(
            "Game did not pass final validation. Do not distribute this project; "
            "inspect final_validation.issues first.",
            file=sys.stderr,
        )
        return 1
    if game_validator_ai.get("status") != "passed":
        print(
            "Game passed hard validation but did not pass the independent Validator AI review. "
            "Inspect game_validator_ai.findings before distribution.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

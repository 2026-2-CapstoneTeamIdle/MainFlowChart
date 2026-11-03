"""Generate one managed image through the common node runner."""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from mainflow.ArtifactManager import ArtifactManager
from MCP import ImageGenerationOptions, ImageRunResult, bind_mcp_tools, run_node_llm


async def _image_node(state: dict[str, Any]) -> ImageRunResult:
    result = await run_node_llm(
        state["prompt"],
        ai=state["ai"],
        output="image",
        image_options=ImageGenerationOptions(
            size=state["size"],
            steps=state["steps"],
            filename_prefix=state["filename_prefix"],
        ),
    )
    if not isinstance(result, ImageRunResult):
        raise TypeError("Image check received a text result")
    return result


async def run_check(args: argparse.Namespace) -> dict[str, Any]:
    """Create or reuse a project and run the exact workflow-facing image API."""

    artifact_manager = ArtifactManager()
    project_id = args.project_id or artifact_manager.create_project()
    node = bind_mcp_tools("generate_image", _image_node)
    result = await node(
        {
            "project_id": project_id,
            "prompt": args.prompt,
            "ai": args.ai,
            "size": args.size,
            "steps": args.steps,
            "filename_prefix": args.filename_prefix,
        }
    )
    return {
        "project_id": project_id,
        "provider": result.provider,
        "model": result.model,
        "size": result.size,
        "artifacts": list(result.artifacts),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prompt",
        default="pixel art side-view platformer target screenshot, forest ruins, no text",
    )
    parser.add_argument("--project-id")
    parser.add_argument("--ai", default="sd_turbo")
    parser.add_argument("--size", default="512x512")
    parser.add_argument("--steps", type=int, default=2)
    parser.add_argument("--filename-prefix", default="local_image_check")
    return parser.parse_args()


def main() -> None:
    report = asyncio.run(run_check(_parse_args()))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

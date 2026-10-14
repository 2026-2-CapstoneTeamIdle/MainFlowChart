"""Verify that Gemini reads a workspace file through the project MCP server."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
from typing import Any

from mainflow.ArtifactManager import ArtifactManager
from MCP.llm_config import LLMSettings
from MCP.llm_providers import create_llm_provider
from MCP.llm_runner import MCPToolLLMRunner
from MCP.manager import MCPManager

DEFAULT_MODEL = "gemini-3-flash-preview"
TEST_RELATIVE_PATH = "data/mcp_gemini_read_test.txt"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a live Gemini -> MCP -> workspace file-read check."
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("GEMINI_MODEL", DEFAULT_MODEL),
        help="Gemini model name (default: GEMINI_MODEL or gemini-3-flash-preview)",
    )
    return parser.parse_args()


def _safe_error_details(error: BaseException) -> list[dict[str, Any]]:
    if isinstance(error, BaseExceptionGroup):
        details: list[dict[str, Any]] = []
        for nested in error.exceptions:
            details.extend(_safe_error_details(nested))
        return details

    detail: dict[str, Any] = {"type": type(error).__name__}
    for attribute in ("code", "status_code"):
        value = getattr(error, attribute, None)
        if isinstance(value, (int, str)):
            detail[attribute] = value
    return [detail]


async def run_check(model: str) -> dict[str, Any]:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set")

    marker = f"MCP_GEMINI_READ_SUCCESS_{secrets.token_hex(6).upper()}"
    artifact_manager = ArtifactManager()
    project_id = artifact_manager.create_project()
    artifact_manager.write_project_text(project_id, TEST_RELATIVE_PATH, marker)

    prompt = (
        "Use the read_project_text tool to read the UTF-8 test file. "
        "Do not guess its contents. Reply with the exact file content only. "
        f"project_id={project_id}, relative_path={TEST_RELATIVE_PATH}"
    )
    settings = LLMSettings.from_environment(
        node_name="user_input",
        provider="gemini",
        model=model,
    )
    provider = create_llm_provider(settings)
    try:
        runner = MCPToolLLMRunner(MCPManager("user_input"), provider)
        result = await runner.run(prompt, require_tool=True)
    finally:
        await provider.aclose()

    tool_calls = [{"name": call.name, "arguments": call.arguments} for call in result.tool_calls]
    final_output = result.text

    read_call_observed = any(
        call["name"] == "read_project_text"
        and call["arguments"].get("project_id") == project_id
        and call["arguments"].get("relative_path") == TEST_RELATIVE_PATH
        for call in tool_calls
    )
    marker_returned = marker in final_output
    status = "passed" if read_call_observed and marker_returned else "failed"
    report = {
        "status": status,
        "model": model,
        "project_id": project_id,
        "relative_path": TEST_RELATIVE_PATH,
        "api_key_detected": True,
        "read_call_observed": read_call_observed,
        "marker_returned_by_model": marker_returned,
        "tool_calls": tool_calls,
        "final_output": final_output,
    }
    if status != "passed":
        raise RuntimeError("Gemini response did not prove the MCP file read")
    return report


def main() -> None:
    args = _parse_args()
    try:
        report = asyncio.run(run_check(args.model))
    except Exception as error:
        print(
            json.dumps(
                {
                    "status": "error",
                    "error_type": type(error).__name__,
                    "message": "Gemini MCP integration check failed",
                    "details": _safe_error_details(error),
                },
                ensure_ascii=False,
            )
        )
        raise SystemExit(1) from None
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

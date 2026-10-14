"""Verify that Gemini reads a workspace file through the project MCP server."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
from typing import Any

from google import genai
from google.genai import types

from mainflow.ArtifactManager import ArtifactManager
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


def _tool_payload(result: dict[str, Any]) -> dict[str, Any]:
    payload = result["structured_content"]
    if payload is not None:
        return payload
    return {
        "is_error": result["is_error"],
        "content": result["content"],
    }


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
    contents: list[types.Content] = [
        types.Content(role="user", parts=[types.Part.from_text(text=prompt)])
    ]
    tool_calls: list[dict[str, Any]] = []
    final_output = ""

    client = genai.Client(api_key=api_key)
    try:
        async with MCPManager("user_input").connect() as mcp_session:
            definitions = await mcp_session.tool_definitions()
            read_definitions = [
                definition
                for definition in definitions
                if definition["name"] == "read_project_text"
            ]
            if len(read_definitions) != 1:
                raise RuntimeError("read_project_text is not available to user_input")

            definition = read_definitions[0]
            tool = types.Tool(
                function_declarations=[
                    types.FunctionDeclaration(
                        name=definition["name"],
                        description=definition["description"],
                        parameters_json_schema=definition["input_schema"],
                    )
                ]
            )

            for turn in range(4):
                mode = "ANY" if turn == 0 else "AUTO"
                response = await client.aio.models.generate_content(
                    model=model,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        temperature=0,
                        tools=[tool],
                        automatic_function_calling=types.AutomaticFunctionCallingConfig(
                            disable=True
                        ),
                        tool_config=types.ToolConfig(
                            function_calling_config=types.FunctionCallingConfig(
                                mode=mode,
                                allowed_function_names=(
                                    ["read_project_text"] if mode == "ANY" else None
                                ),
                            )
                        ),
                    ),
                )
                if not response.candidates or response.candidates[0].content is None:
                    raise RuntimeError("Gemini returned no candidate content")
                contents.append(response.candidates[0].content)

                calls_this_turn = response.function_calls or []
                if not calls_this_turn:
                    final_output = (response.text or "").strip()
                    break

                response_parts: list[types.Part] = []
                for call in calls_this_turn:
                    if not call.name:
                        raise RuntimeError("Gemini returned a function call without a name")
                    arguments = dict(call.args or {})
                    result = await mcp_session.call_tool(call.name, arguments)
                    tool_calls.append({"name": call.name, "arguments": arguments})
                    response_parts.append(
                        types.Part.from_function_response(
                            name=call.name,
                            response=_tool_payload(result),
                        )
                    )
                contents.append(types.Content(role="tool", parts=response_parts))
            else:
                raise RuntimeError("Gemini did not finish after four tool-call turns")
    finally:
        await client.aio.aclose()

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

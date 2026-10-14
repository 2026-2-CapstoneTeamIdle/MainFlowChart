"""Node-specific MCP tool allowlists."""

from __future__ import annotations

LIST_PROJECT_FILES = "list_project_files"
READ_PROJECT_TEXT = "read_project_text"
WRITE_PROJECT_TEXT = "write_project_text"

READ_TOOLS = frozenset({LIST_PROJECT_FILES, READ_PROJECT_TEXT})
WORKING_FILE_TOOLS = frozenset({*READ_TOOLS, WRITE_PROJECT_TEXT})

# The server may grow new tools without exposing them to every LLM. A node only
# receives definitions listed here, and MCPManager rejects unlisted calls even
# if a model attempts to invoke one by name.
NODE_TOOL_ALLOWLIST: dict[str, frozenset[str]] = {
    "user_input": READ_TOOLS,
    "parse_input": WORKING_FILE_TOOLS,
    "analysis": WORKING_FILE_TOOLS,
    "logic_analysis": WORKING_FILE_TOOLS,
    "design_game_logic": WORKING_FILE_TOOLS,
    "generate_image": WORKING_FILE_TOOLS,
    "generate_sound": WORKING_FILE_TOOLS,
    "validate_game": WORKING_FILE_TOOLS,
    "create_asset_validation_spec": WORKING_FILE_TOOLS,
    "validate_image": WORKING_FILE_TOOLS,
    "validate_sound": WORKING_FILE_TOOLS,
    "apply_assets_to_game": WORKING_FILE_TOOLS,
    "final_validation": WORKING_FILE_TOOLS,
}


def allowed_tools_for_node(node_name: str) -> frozenset[str]:
    """Return a node's explicit allowlist and reject unknown node names."""

    try:
        return NODE_TOOL_ALLOWLIST[node_name]
    except KeyError as error:
        raise KeyError(f"No MCP tool policy is registered for node: {node_name}") from error

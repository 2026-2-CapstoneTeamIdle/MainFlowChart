"""Assemble the MainFlowChart LangGraph without embedding Node implementations."""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from mainflow.contracts import WorkflowState
from mainflow.nodes import (
    analysis_node,
    apply_assets_to_game_node,
    create_asset_validation_spec_node,
    design_game_logic_node,
    final_validation_node,
    generate_image_node,
    generate_sound_node,
    game_quality_validator_node,
    logic_analysis_node,
    parse_input_node,
    user_input_node,
    validate_game_node,
    validate_image_node,
    validate_sound_node,
)
from MCP import bind_mcp_tools


def build_graph():
    """Register workflow Nodes and preserve the authoritative Edge topology."""
    graph = StateGraph(WorkflowState)

    def add_node(name, node):
        graph.add_node(name, bind_mcp_tools(name, node))

    # Nodes
    add_node("user_input", user_input_node)
    add_node("parse_input", parse_input_node)

    add_node("analysis", analysis_node)
    add_node("logic_analysis", logic_analysis_node)

    add_node("generate_image", generate_image_node)
    add_node("design_game_logic", design_game_logic_node)
    add_node("generate_sound", generate_sound_node)

    add_node("validate_game", validate_game_node)

    add_node(
        "create_asset_validation_spec",
        create_asset_validation_spec_node,
    )

    add_node("validate_image", validate_image_node)
    add_node("validate_sound", validate_sound_node)

    add_node(
        "apply_assets_to_game",
        apply_assets_to_game_node,
    )

    add_node(
        "final_validation",
        final_validation_node,
    )
    add_node("game_quality_validator", game_quality_validator_node)

    # --------------------------------------------------------
    # Flow
    # --------------------------------------------------------
    graph.add_edge(START, "user_input")
    graph.add_edge("user_input", "parse_input")

    # Parse the one-sentence condition before the parallel generation branches.
    graph.add_edge("parse_input", "analysis")
    graph.add_edge("analysis", "logic_analysis")

    # 1. Design the Unity project and its explicit image/sound request JSON first.
    graph.add_edge(
        "logic_analysis",
        "design_game_logic",
    )

    # 2. Image / game validation / sound work can proceed from the game design.
    graph.add_edge(
        "design_game_logic",
        "generate_image",
    )
    graph.add_edge(
        "design_game_logic",
        "generate_sound",
    )
    graph.add_edge(
        "design_game_logic",
        "validate_game",
    )
    graph.add_edge(
        "validate_game",
        "create_asset_validation_spec",
    )

    # 3. Image validation waits for:
    #    - image generation
    #    - asset validation spec
    graph.add_edge(
        [
            "generate_image",
            "create_asset_validation_spec",
        ],
        "validate_image",
    )

    # 4. Sound validation waits for:
    #    - sound generation
    #    - asset validation spec
    graph.add_edge(
        [
            "generate_sound",
            "create_asset_validation_spec",
        ],
        "validate_sound",
    )

    # 5. Apply assets only after both validations are done
    graph.add_edge(
        [
            "validate_image",
            "validate_sound",
        ],
        "apply_assets_to_game",
    )

    # 6. Final validation using LogicAnalysis criteria
    graph.add_edge(
        "apply_assets_to_game",
        "final_validation",
    )

    graph.add_edge("final_validation", "game_quality_validator")
    graph.add_edge("game_quality_validator", END)

    return graph.compile()


if __name__ == "__main__":
    app = build_graph()

    print("\n=== Game Agent Flow 시작 ===\n")

    final_state = app.invoke({})

    print("\n=== Game Agent Flow 종료 ===")
    print("최종 State:")
    print(final_state)

    # app = build_graph()
    # png_data = app.get_graph().draw_mermaid_png()
    # with open("docs/assets/langgraph_flow.png", "wb") as file:
    #     file.write(png_data)

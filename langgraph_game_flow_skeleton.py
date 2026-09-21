from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph


# ============================================================
# State
# - 실제 이미지/사운드/게임 파일 처리는 아직 하지 않음
# - 각 단계가 지나갔다는 표시와 임시 데이터만 저장
# ============================================================
class WorkflowState(TypedDict, total=False):
    # User input
    image_style: str
    genre: str
    quality: str
    parsed_request: dict[str, Any]

    # "맨 처음" 만들어 두는 최종 검증 기준서
    initial_final_validation_spec: dict[str, Any]

    # Parallel generation outputs (temporary placeholders)
    image_draft: dict[str, Any]
    game_logic_draft: dict[str, Any]
    sound_draft: dict[str, Any]

    # Game validation
    game_validation_result: dict[str, Any]

    # Validation sheet for image/sound assets
    asset_validation_spec: dict[str, Any]

    # Asset validation results
    image_validation_result: dict[str, Any]
    sound_validation_result: dict[str, Any]

    # Game after validated assets are applied
    integrated_game: dict[str, Any]

    # Final validation
    final_validation_result: dict[str, Any]


def log(message: str) -> None:
    print(f"[FLOW] {message}")


# ============================================================
# Nodes
# ============================================================
def user_input_node(state: WorkflowState) -> dict[str, Any]:
    """
    임시 GUI:
    - 이미지 스타일
    - 장르
    - 퀄리티
    """
    log("유저 입력 창을 표시합니다.")

    import tkinter as tk
    from tkinter import ttk

    result: dict[str, str] = {}

    root = tk.Tk()
    root.title("Game Agent - 임시 입력")
    root.resizable(False, False)

    frame = ttk.Frame(root, padding=20)
    frame.grid(row=0, column=0)

    ttk.Label(frame, text="이미지 스타일").grid(
        row=0, column=0, sticky="w", padx=5, pady=8
    )
    image_style_var = tk.StringVar(value="Pixel Art")
    image_style_box = ttk.Combobox(
        frame,
        textvariable=image_style_var,
        state="readonly",
        width=24,
        values=[
            "Pixel Art",
            "Anime",
            "Cartoon",
            "Realistic",
            "Low Poly",
        ],
    )
    image_style_box.grid(row=0, column=1, padx=5, pady=8)

    ttk.Label(frame, text="게임 장르").grid(
        row=1, column=0, sticky="w", padx=5, pady=8
    )
    genre_var = tk.StringVar(value="Action")
    genre_box = ttk.Combobox(
        frame,
        textvariable=genre_var,
        state="readonly",
        width=24,
        values=[
            "Action",
            "RPG",
            "Platformer",
            "Puzzle",
            "Simulation",
        ],
    )
    genre_box.grid(row=1, column=1, padx=5, pady=8)

    ttk.Label(frame, text="퀄리티").grid(
        row=2, column=0, sticky="w", padx=5, pady=8
    )
    quality_var = tk.StringVar(value="Medium")
    quality_box = ttk.Combobox(
        frame,
        textvariable=quality_var,
        state="readonly",
        width=24,
        values=[
            "Low",
            "Medium",
            "High",
        ],
    )
    quality_box.grid(row=2, column=1, padx=5, pady=8)

    def submit() -> None:
        result["image_style"] = image_style_var.get()
        result["genre"] = genre_var.get()
        result["quality"] = quality_var.get()
        root.destroy()

    start_button = ttk.Button(
        frame,
        text="START",
        command=submit,
    )
    start_button.grid(
        row=3,
        column=0,
        columnspan=2,
        sticky="ew",
        padx=5,
        pady=(15, 5),
    )

    root.protocol("WM_DELETE_WINDOW", submit)
    root.mainloop()

    log(
        "입력 완료 "
        f"(스타일={result['image_style']}, "
        f"장르={result['genre']}, "
        f"퀄리티={result['quality']})"
    )

    return result


def parse_input_node(state: WorkflowState) -> dict[str, Any]:
    log("유저 입력을 파싱합니다.")

    # TODO: 이후 AdviserAI / LLM을 이용한 실제 요구사항 파싱
    return {
        "parsed_request": {
            "image_style": state["image_style"],
            "genre": state["genre"],
            "quality": state["quality"],
        }
    }


def create_initial_final_validation_spec_node(
    state: WorkflowState,
) -> dict[str, Any]:
    log("최종 검증에 사용할 최초 검증서를 생성합니다.")

    # TODO: 실제 최종 검증 기준 작성
    return {
        "initial_final_validation_spec": {}
    }


# ------------------------------------------------------------
# 1) Image / Game / Sound generation - PARALLEL
# ------------------------------------------------------------
def generate_image_node(state: WorkflowState) -> dict[str, Any]:
    log("이미지 에셋을 생성합니다. (현재는 뼈대만 실행)")

    # TODO: 실제 이미지 생성
    return {
        "image_draft": {}
    }


def design_game_logic_node(state: WorkflowState) -> dict[str, Any]:
    log(
        "게임 로직을 설계합니다. "
        "(이미지/사운드는 임시 에셋으로 가정)"
    )

    # TODO: 실제 게임 로직 / Unity / Godot 코드 설계
    return {
        "game_logic_draft": {}
    }


def generate_sound_node(state: WorkflowState) -> dict[str, Any]:
    log("사운드 에셋을 생성합니다. (현재는 뼈대만 실행)")

    # TODO: 실제 사운드 생성
    return {
        "sound_draft": {}
    }


# ------------------------------------------------------------
# 2) Game validation -> asset validation sheet
# ------------------------------------------------------------
def validate_game_node(state: WorkflowState) -> dict[str, Any]:
    log("임시 에셋을 사용해 설계된 게임을 검증합니다.")

    # TODO: Unity Test Framework / build / logic validation
    return {
        "game_validation_result": {}
    }


def create_asset_validation_spec_node(
    state: WorkflowState,
) -> dict[str, Any]:
    log(
        "게임 검증 결과를 바탕으로 "
        "이미지/사운드 에셋 검증서를 생성합니다."
    )

    # TODO: game_validation_result를 이용해 실제 검증 기준 생성
    return {
        "asset_validation_spec": {}
    }


# ------------------------------------------------------------
# 3) Validate generated image / sound
# Each node must wait for:
# - its generated asset
# - asset_validation_spec
# ------------------------------------------------------------
def validate_image_node(state: WorkflowState) -> dict[str, Any]:
    log(
        "유저 입력 + 에셋 검증서를 바탕으로 "
        "이미지 에셋을 검증합니다."
    )

    # TODO: 이미지 검증
    return {
        "image_validation_result": {}
    }


def validate_sound_node(state: WorkflowState) -> dict[str, Any]:
    log(
        "유저 입력 + 에셋 검증서를 바탕으로 "
        "사운드 에셋을 검증합니다."
    )

    # TODO: 사운드 검증
    return {
        "sound_validation_result": {}
    }


# ------------------------------------------------------------
# 4) Apply validated assets to the game
# ------------------------------------------------------------
def apply_assets_to_game_node(
    state: WorkflowState,
) -> dict[str, Any]:
    log(
        "검증을 통과한 이미지/사운드 에셋을 "
        "게임에 적용합니다."
    )

    # TODO: 실제 Unity/Godot 프로젝트에 에셋 적용
    return {
        "integrated_game": {}
    }


# ------------------------------------------------------------
# 5) Final validation
# ------------------------------------------------------------
def final_validation_node(
    state: WorkflowState,
) -> dict[str, Any]:
    log(
        "맨 처음 생성한 최종 검증서를 기준으로 "
        "완성된 게임을 최종 검증합니다."
    )

    # TODO: initial_final_validation_spec 기준 최종 검증
    return {
        "final_validation_result": {}
    }


# ============================================================
# Graph
# ============================================================
def build_graph():
    graph = StateGraph(WorkflowState)

    # Nodes
    graph.add_node("user_input", user_input_node)
    graph.add_node("parse_input", parse_input_node)

    graph.add_node(
        "create_initial_final_validation_spec",
        create_initial_final_validation_spec_node,
    )

    graph.add_node("generate_image", generate_image_node)
    graph.add_node("design_game_logic", design_game_logic_node)
    graph.add_node("generate_sound", generate_sound_node)

    graph.add_node("validate_game", validate_game_node)

    graph.add_node(
        "create_asset_validation_spec",
        create_asset_validation_spec_node,
    )

    graph.add_node("validate_image", validate_image_node)
    graph.add_node("validate_sound", validate_sound_node)

    graph.add_node(
        "apply_assets_to_game",
        apply_assets_to_game_node,
    )

    graph.add_node(
        "final_validation",
        final_validation_node,
    )

    # --------------------------------------------------------
    # Flow
    # --------------------------------------------------------
    graph.add_edge(START, "user_input")
    graph.add_edge("user_input", "parse_input")

    # 최초 최종 검증서를 먼저 작성
    graph.add_edge(
        "parse_input",
        "create_initial_final_validation_spec",
    )

    # 1. Image / Game / Sound generation in parallel
    graph.add_edge(
        "create_initial_final_validation_spec",
        "generate_image",
    )
    graph.add_edge(
        "create_initial_final_validation_spec",
        "design_game_logic",
    )
    graph.add_edge(
        "create_initial_final_validation_spec",
        "generate_sound",
    )

    # 2. Game branch validation
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

    # 6. Final validation using the initial final validation spec
    graph.add_edge(
        "apply_assets_to_game",
        "final_validation",
    )

    graph.add_edge("final_validation", END)

    return graph.compile()


if __name__ == "__main__":
    app = build_graph()

    print("\n=== Game Agent Flow 시작 ===\n")

    final_state = app.invoke({})

    print("\n=== Game Agent Flow 종료 ===")
    print("최종 State:")
    print(final_state)

    ###
    #app = build_graph()
    #
    #png_data = app.get_graph().draw_mermaid_png()
    #
    #with open("langgraph_flow.png", "wb") as f:
    #    f.write(png_data)

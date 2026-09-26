from __future__ import annotations

from typing import cast

from langgraph.graph import END, START, StateGraph

from ArtifactManager import ArtifactManager
from contracts import (
    CONTRACT_VERSION,
    ApplyAssetsAgentInput,
    ApplyAssetsAgentOutput,
    AssetValidationSpec,
    AssetValidationSpecAgentInput,
    AssetValidationSpecAgentOutput,
    DesignGameLogicAgentInput,
    DesignGameLogicAgentOutput,
    FinalValidationResult,
    FinalValidationAgentInput,
    FinalValidationAgentOutput,
    GenerateImageAgentInput,
    GenerateImageAgentOutput,
    GenerateSoundAgentInput,
    GenerateSoundAgentOutput,
    GameLogicDraft,
    GameValidationResult,
    ImageDraft,
    ImageValidationResult,
    InitialFinalValidationSpec,
    InitialValidationSpecAgentInput,
    InitialValidationSpecAgentOutput,
    ParseInputAgentInput,
    ParseInputAgentOutput,
    ParsedRequest,
    SoundDraft,
    SoundValidationResult,
    IntegratedGame,
    UserInputAgentInput,
    UserInputAgentOutput,
    ValidateGameAgentInput,
    ValidateGameAgentOutput,
    ValidateImageAgentInput,
    ValidateImageAgentOutput,
    ValidateSoundAgentInput,
    ValidateSoundAgentOutput,
    WorkflowState,
)


def log(message: str) -> None:
    print(f"[FLOW] {message}")


# ============================================================
# Nodes
# ============================================================
def user_input_node(state: UserInputAgentInput) -> UserInputAgentOutput:
    """
    임시 GUI:
    - 이미지 스타일
    - 장르
    - 퀄리티
    """
    if all(key in state for key in ("image_style", "genre", "quality")):
        log("초기 State의 입력값을 사용해 GUI를 건너뜁니다.")
        return {
            "image_style": state["image_style"],
            "genre": state["genre"],
            "quality": state["quality"],
        }

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

    # Combobox values are restricted to the Literal choices in contracts.py.
    return cast(UserInputAgentOutput, result)


def parse_input_node(state: ParseInputAgentInput) -> ParseInputAgentOutput:
    log("유저 입력을 파싱합니다.")

    # TODO: 이후 AdviserAI / LLM을 이용한 실제 요구사항 파싱
    manager = ArtifactManager()
    project_id = manager.create_project()
    parsed_request: ParsedRequest = {
        "contract_version": CONTRACT_VERSION,
        "image_style": state["image_style"],
        "genre": state["genre"],
        "quality": state["quality"],
    }
    return {
        "project_id": project_id,
        "parsed_request": manager.write_json(
            project_id,
            "data",
            "parsed_request.json",
            parsed_request,
            producer="parse_input",
        ),
    }


def create_initial_final_validation_spec_node(
    state: InitialValidationSpecAgentInput,
) -> InitialValidationSpecAgentOutput:
    log("최종 검증에 사용할 최초 검증서를 생성합니다.")

    manager = ArtifactManager()
    # Read through ArtifactManager so checksum and project boundaries are checked.
    cast(ParsedRequest, manager.read_json(state["parsed_request"]))

    # TODO: 실제 최종 검증 기준 작성
    spec: InitialFinalValidationSpec = {
        "contract_version": CONTRACT_VERSION,
        "spec_id": "initial-final-validation",
        "criteria": [],
    }
    return {
        "initial_final_validation_spec": manager.write_json(
            state["project_id"],
            "validation",
            "initial_final_validation_spec.json",
            spec,
            producer="create_initial_final_validation_spec",
        )
    }


# ------------------------------------------------------------
# 1) Image / Game / Sound generation - PARALLEL
# ------------------------------------------------------------
def generate_image_node(
    state: GenerateImageAgentInput,
) -> GenerateImageAgentOutput:
    log("이미지 에셋을 생성합니다. (현재는 뼈대만 실행)")

    manager = ArtifactManager()
    cast(ParsedRequest, manager.read_json(state["parsed_request"]))
    cast(
        InitialFinalValidationSpec,
        manager.read_json(state["initial_final_validation_spec"]),
    )

    # TODO: 실제 이미지 생성
    draft: ImageDraft = {
        "contract_version": CONTRACT_VERSION,
        "draft_id": "image-draft",
        "status": "pending",
        "assets": [],
        "notes": ["이미지 생성 Agent 구현 전 placeholder"],
    }
    return {
        "image_draft": manager.write_json(
            state["project_id"],
            "image",
            "image_draft.json",
            draft,
            producer="generate_image",
        )
    }


def design_game_logic_node(
    state: DesignGameLogicAgentInput,
) -> DesignGameLogicAgentOutput:
    log(
        "게임 로직을 설계합니다. "
        "(이미지/사운드는 임시 에셋으로 가정)"
    )

    manager = ArtifactManager()
    cast(ParsedRequest, manager.read_json(state["parsed_request"]))
    cast(
        InitialFinalValidationSpec,
        manager.read_json(state["initial_final_validation_spec"]),
    )

    # TODO: 실제 게임 로직 / Unity / Godot 코드 설계
    draft: GameLogicDraft = {
        "contract_version": CONTRACT_VERSION,
        "draft_id": "game-logic-draft",
        "status": "pending",
        "engine": "TBD",
        "entry_scene": None,
        "source_artifacts": [],
        "required_image_asset_ids": [],
        "required_sound_asset_ids": [],
        "notes": ["게임 로직 설계 Agent 구현 전 placeholder"],
    }
    return {
        "game_logic_draft": manager.write_json(
            state["project_id"],
            "game",
            "game_logic_draft.json",
            draft,
            producer="design_game_logic",
        )
    }


def generate_sound_node(
    state: GenerateSoundAgentInput,
) -> GenerateSoundAgentOutput:
    log("사운드 에셋을 생성합니다. (현재는 뼈대만 실행)")

    manager = ArtifactManager()
    cast(ParsedRequest, manager.read_json(state["parsed_request"]))
    cast(
        InitialFinalValidationSpec,
        manager.read_json(state["initial_final_validation_spec"]),
    )

    # TODO: 실제 사운드 생성
    draft: SoundDraft = {
        "contract_version": CONTRACT_VERSION,
        "draft_id": "sound-draft",
        "status": "pending",
        "assets": [],
        "notes": ["사운드 생성 Agent 구현 전 placeholder"],
    }
    return {
        "sound_draft": manager.write_json(
            state["project_id"],
            "sound",
            "sound_draft.json",
            draft,
            producer="generate_sound",
        )
    }


# ------------------------------------------------------------
# 2) Game validation -> asset validation sheet
# ------------------------------------------------------------
def validate_game_node(
    state: ValidateGameAgentInput,
) -> ValidateGameAgentOutput:
    log("임시 에셋을 사용해 설계된 게임을 검증합니다.")

    manager = ArtifactManager()
    cast(ParsedRequest, manager.read_json(state["parsed_request"]))
    cast(
        InitialFinalValidationSpec,
        manager.read_json(state["initial_final_validation_spec"]),
    )
    cast(GameLogicDraft, manager.read_json(state["game_logic_draft"]))

    # TODO: Unity Test Framework / build / logic validation
    result: GameValidationResult = {
        "contract_version": CONTRACT_VERSION,
        "status": "pending",
        "checks": [],
        "issues": [],
    }
    return {
        "game_validation_result": manager.write_json(
            state["project_id"],
            "validation",
            "game_validation_result.json",
            result,
            producer="validate_game",
        )
    }


def create_asset_validation_spec_node(
    state: AssetValidationSpecAgentInput,
) -> AssetValidationSpecAgentOutput:
    log(
        "게임 검증 결과를 바탕으로 "
        "이미지/사운드 에셋 검증서를 생성합니다."
    )

    manager = ArtifactManager()
    cast(ParsedRequest, manager.read_json(state["parsed_request"]))
    cast(
        GameValidationResult,
        manager.read_json(state["game_validation_result"]),
    )

    # TODO: game_validation_result를 이용해 실제 검증 기준 생성
    spec: AssetValidationSpec = {
        "contract_version": CONTRACT_VERSION,
        "spec_id": "asset-validation",
        "image_criteria": [],
        "sound_criteria": [],
    }
    return {
        "asset_validation_spec": manager.write_json(
            state["project_id"],
            "validation",
            "asset_validation_spec.json",
            spec,
            producer="create_asset_validation_spec",
        )
    }


# ------------------------------------------------------------
# 3) Validate generated image / sound
# Each node must wait for:
# - its generated asset
# - asset_validation_spec
# ------------------------------------------------------------
def validate_image_node(
    state: ValidateImageAgentInput,
) -> ValidateImageAgentOutput:
    log(
        "유저 입력 + 에셋 검증서를 바탕으로 "
        "이미지 에셋을 검증합니다."
    )

    manager = ArtifactManager()
    cast(ParsedRequest, manager.read_json(state["parsed_request"]))
    cast(ImageDraft, manager.read_json(state["image_draft"]))
    cast(AssetValidationSpec, manager.read_json(state["asset_validation_spec"]))

    # TODO: 이미지 검증
    result: ImageValidationResult = {
        "contract_version": CONTRACT_VERSION,
        "status": "pending",
        "checks": [],
        "issues": [],
        "validated_asset_ids": [],
    }
    return {
        "image_validation_result": manager.write_json(
            state["project_id"],
            "validation",
            "image_validation_result.json",
            result,
            producer="validate_image",
        )
    }


def validate_sound_node(
    state: ValidateSoundAgentInput,
) -> ValidateSoundAgentOutput:
    log(
        "유저 입력 + 에셋 검증서를 바탕으로 "
        "사운드 에셋을 검증합니다."
    )

    manager = ArtifactManager()
    cast(ParsedRequest, manager.read_json(state["parsed_request"]))
    cast(SoundDraft, manager.read_json(state["sound_draft"]))
    cast(AssetValidationSpec, manager.read_json(state["asset_validation_spec"]))

    # TODO: 사운드 검증
    result: SoundValidationResult = {
        "contract_version": CONTRACT_VERSION,
        "status": "pending",
        "checks": [],
        "issues": [],
        "validated_asset_ids": [],
    }
    return {
        "sound_validation_result": manager.write_json(
            state["project_id"],
            "validation",
            "sound_validation_result.json",
            result,
            producer="validate_sound",
        )
    }


# ------------------------------------------------------------
# 4) Apply validated assets to the game
# ------------------------------------------------------------
def apply_assets_to_game_node(
    state: ApplyAssetsAgentInput,
) -> ApplyAssetsAgentOutput:
    log(
        "검증을 통과한 이미지/사운드 에셋을 "
        "게임에 적용합니다."
    )

    manager = ArtifactManager()
    cast(GameLogicDraft, manager.read_json(state["game_logic_draft"]))
    cast(ImageDraft, manager.read_json(state["image_draft"]))
    cast(SoundDraft, manager.read_json(state["sound_draft"]))
    cast(
        ImageValidationResult,
        manager.read_json(state["image_validation_result"]),
    )
    cast(
        SoundValidationResult,
        manager.read_json(state["sound_validation_result"]),
    )

    # TODO: 실제 Unity/Godot 프로젝트에 에셋 적용
    integrated_game: IntegratedGame = {
        "contract_version": CONTRACT_VERSION,
        "status": "pending",
        "entry_artifact": None,
        "game_artifacts": [],
        "applied_image_asset_ids": [],
        "applied_sound_asset_ids": [],
        "notes": ["에셋 통합 Agent 구현 전 placeholder"],
    }
    return {
        "integrated_game": manager.write_json(
            state["project_id"],
            "game",
            "integrated_game.json",
            integrated_game,
            producer="apply_assets_to_game",
        )
    }


# ------------------------------------------------------------
# 5) Final validation
# ------------------------------------------------------------
def final_validation_node(
    state: FinalValidationAgentInput,
) -> FinalValidationAgentOutput:
    log(
        "맨 처음 생성한 최종 검증서를 기준으로 "
        "완성된 게임을 최종 검증합니다."
    )

    manager = ArtifactManager()
    cast(
        InitialFinalValidationSpec,
        manager.read_json(state["initial_final_validation_spec"]),
    )
    cast(IntegratedGame, manager.read_json(state["integrated_game"]))

    # TODO: initial_final_validation_spec 기준 최종 검증
    result: FinalValidationResult = {
        "contract_version": CONTRACT_VERSION,
        "status": "pending",
        "checks": [],
        "issues": [],
    }
    return {
        "final_validation_result": manager.write_json(
            state["project_id"],
            "validation",
            "final_validation_result.json",
            result,
            producer="final_validation",
        )
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

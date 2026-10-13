"""Collect the initial game-generation request."""

from __future__ import annotations

from typing import cast

from mainflow.contracts import UserInputAgentInput, UserInputAgentOutput
from mainflow.nodes._common import log


# Node 계약
# - 이전 Node: START
# - 입력 State: image_style, mood_style, genre, condition, custom_image_path(선택)
# - 입력 파일: 없음
# - 출력 State: image_style, mood_style, genre, condition, custom_image_path(선택)
# - 출력 파일: 없음
# - 다음 Node: parse_input
def user_input_node(state: UserInputAgentInput) -> UserInputAgentOutput:
    """Use supplied values or collect them through the temporary desktop GUI."""
    required = ("image_style", "mood_style", "genre", "condition")
    if all(key in state for key in required):
        if state["image_style"] == "Custom" and not state.get("custom_image_path"):
            raise ValueError("Custom image style requires custom_image_path")
        log("초기 State의 입력값을 사용해 GUI를 건너뜁니다.")
        output: UserInputAgentOutput = {
            "image_style": state["image_style"],
            "mood_style": state["mood_style"],
            "genre": state["genre"],
            "condition": state["condition"],
        }
        if "custom_image_path" in state:
            output["custom_image_path"] = state["custom_image_path"]
        return output

    log("유저 입력 창을 표시합니다.")

    import tkinter as tk
    from tkinter import ttk

    result: dict[str, str] = {}

    root = tk.Tk()
    root.title("Game Agent - 임시 입력")
    root.resizable(False, False)

    frame = ttk.Frame(root, padding=20)
    frame.grid(row=0, column=0)

    ttk.Label(frame, text="이미지 스타일").grid(row=0, column=0, sticky="w", padx=5, pady=8)
    image_style_var = tk.StringVar(value="Pixel Art")
    image_style_box = ttk.Combobox(
        frame,
        textvariable=image_style_var,
        state="readonly",
        width=24,
        values=["Pixel Art", "Anime", "Cartoon", "Realistic", "Low Poly", "Custom"],
    )
    image_style_box.grid(row=0, column=1, padx=5, pady=8)

    ttk.Label(frame, text="분위기 스타일").grid(row=1, column=0, sticky="w", padx=5, pady=8)
    mood_style_var = tk.StringVar(value="Fantasy")
    mood_style_box = ttk.Combobox(
        frame,
        textvariable=mood_style_var,
        state="readonly",
        width=24,
        values=["Cyberpunk", "Medieval", "Modern", "Fantasy", "Horror", "Cozy"],
    )
    mood_style_box.grid(row=1, column=1, padx=5, pady=8)

    ttk.Label(frame, text="게임 장르").grid(row=2, column=0, sticky="w", padx=5, pady=8)
    genre_var = tk.StringVar(value="플랫포머")
    genre_box = ttk.Combobox(
        frame,
        textvariable=genre_var,
        state="readonly",
        width=24,
        values=["플랫포머", "타워 디펜스", "카드", "비주얼 노벨", "육성 시뮬레이션", "뱀서류"],
    )
    genre_box.grid(row=2, column=1, padx=5, pady=8)

    ttk.Label(frame, text="조건").grid(row=3, column=0, sticky="w", padx=5, pady=8)
    condition_var = tk.StringVar(value="공격과 8방향 이동이 가능한 게임")
    ttk.Entry(frame, textvariable=condition_var, width=27).grid(row=3, column=1, padx=5, pady=8)

    custom_image_var = tk.StringVar()

    def choose_custom_image() -> None:
        from tkinter import filedialog

        selected = filedialog.askopenfilename(filetypes=[("Image files", "*.png *.jpg *.jpeg")])
        if selected:
            custom_image_var.set(selected)

    ttk.Label(frame, text="Custom 이미지").grid(row=4, column=0, sticky="w", padx=5, pady=8)
    ttk.Button(frame, text="PNG/JPG 선택", command=choose_custom_image).grid(
        row=4, column=1, sticky="ew", padx=5, pady=8
    )

    def submit() -> None:
        result["image_style"] = image_style_var.get()
        result["mood_style"] = mood_style_var.get()
        result["genre"] = genre_var.get()
        result["condition"] = condition_var.get().strip()
        if image_style_var.get() == "Custom":
            if not custom_image_var.get():
                raise ValueError("Custom 이미지 스타일에는 PNG/JPG 파일이 필요합니다.")
            result["custom_image_path"] = custom_image_var.get()
        root.destroy()

    start_button = ttk.Button(frame, text="START", command=submit)
    start_button.grid(
        row=5,
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
        f"분위기={result['mood_style']}, "
        f"장르={result['genre']}, "
        f"조건={result['condition']})"
    )

    # Combobox values are restricted to the Literal choices in contracts.py.
    return cast(UserInputAgentOutput, result)

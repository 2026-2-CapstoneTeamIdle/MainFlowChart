"""Collect the initial game-generation request."""

from __future__ import annotations

from typing import cast

from mainflow.contracts import UserInputAgentInput, UserInputAgentOutput
from mainflow.nodes._common import log


# Node 계약
# - 이전 Node: START
# - 입력 State: image_style, genre, quality (headless 실행에서는 선택값 제공)
# - 입력 파일: 없음
# - 출력 State: image_style, genre, quality
# - 출력 파일: 없음
# - 다음 Node: parse_input
def user_input_node(state: UserInputAgentInput) -> UserInputAgentOutput:
    """Use supplied values or collect them through the temporary desktop GUI."""
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

    ttk.Label(frame, text="이미지 스타일").grid(row=0, column=0, sticky="w", padx=5, pady=8)
    image_style_var = tk.StringVar(value="Pixel Art")
    image_style_box = ttk.Combobox(
        frame,
        textvariable=image_style_var,
        state="readonly",
        width=24,
        values=["Pixel Art", "Anime", "Cartoon", "Realistic", "Low Poly"],
    )
    image_style_box.grid(row=0, column=1, padx=5, pady=8)

    ttk.Label(frame, text="게임 장르").grid(row=1, column=0, sticky="w", padx=5, pady=8)
    genre_var = tk.StringVar(value="Action")
    genre_box = ttk.Combobox(
        frame,
        textvariable=genre_var,
        state="readonly",
        width=24,
        values=["Action", "RPG", "Platformer", "Puzzle", "Simulation"],
    )
    genre_box.grid(row=1, column=1, padx=5, pady=8)

    ttk.Label(frame, text="퀄리티").grid(row=2, column=0, sticky="w", padx=5, pady=8)
    quality_var = tk.StringVar(value="Medium")
    quality_box = ttk.Combobox(
        frame,
        textvariable=quality_var,
        state="readonly",
        width=24,
        values=["Low", "Medium", "High"],
    )
    quality_box.grid(row=2, column=1, padx=5, pady=8)

    def submit() -> None:
        result["image_style"] = image_style_var.get()
        result["genre"] = genre_var.get()
        result["quality"] = quality_var.get()
        root.destroy()

    start_button = ttk.Button(frame, text="START", command=submit)
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

"""Collect and validate the initial game-generation request."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TypeVar, cast, get_args

from mainflow.contracts import (
    GameGenre,
    ImageStyle,
    MoodStyle,
    UserInputAgentInput,
    UserInputAgentOutput,
    Viewpoint,
)
from mainflow.nodes._common import log

Choice = TypeVar("Choice", bound=str)

# Keep UI choices synchronized with contracts.py. Adding a Literal value to the
# contract automatically exposes it to this node without duplicating the list.
IMAGE_STYLE_OPTIONS = cast(tuple[ImageStyle, ...], get_args(ImageStyle))
MOOD_STYLE_OPTIONS = cast(tuple[MoodStyle, ...], get_args(MoodStyle))
GENRE_OPTIONS = cast(tuple[GameGenre, ...], get_args(GameGenre))
VIEWPOINT_OPTIONS = cast(tuple[Viewpoint, ...], get_args(Viewpoint))


def _required_choice(
    state: Mapping[str, object],
    field: str,
    choices: tuple[Choice, ...],
) -> Choice:
    value = state.get(field)
    if not isinstance(value, str) or value not in choices:
        allowed = ", ".join(choices)
        raise ValueError(f"{field} must be one of: {allowed}")
    return cast(Choice, value)


def normalize_user_input(state: Mapping[str, object]) -> UserInputAgentOutput:
    """Return only contract fields after lightweight boundary validation.

    This function intentionally performs no semantic analysis. It keeps the
    user-input and parse-input nodes independent from downstream agents while
    providing one validation path for CLI, web, tests, and the temporary GUI.
    """
    image_style = _required_choice(state, "image_style", IMAGE_STYLE_OPTIONS)
    mood_style = _required_choice(state, "mood_style", MOOD_STYLE_OPTIONS)
    genre = _required_choice(state, "genre", GENRE_OPTIONS)
    viewpoint = _required_choice(state, "viewpoint", VIEWPOINT_OPTIONS)

    condition_value = state.get("condition")
    if not isinstance(condition_value, str) or not condition_value.strip():
        raise ValueError("condition must be a non-empty string")

    output: UserInputAgentOutput = {
        "image_style": image_style,
        "mood_style": mood_style,
        "genre": genre,
        "viewpoint": viewpoint,
        "condition": condition_value.strip(),
    }

    if image_style == "Custom":
        custom_path = state.get("custom_image_path")
        if not isinstance(custom_path, str) or not custom_path.strip():
            raise ValueError("Custom image style requires custom_image_path")
        output["custom_image_path"] = custom_path.strip()

    return output


# Node 계약
# - 이전 Node: START
# - 입력 State: image_style, mood_style, genre, viewpoint, condition, custom_image_path(선택)
# - 입력 파일: 없음
# - 출력 State: image_style, mood_style, genre, viewpoint, condition, custom_image_path(선택)
# - 출력 파일: 없음
# - 다음 Node: parse_input
def user_input_node(state: UserInputAgentInput) -> UserInputAgentOutput:
    """Use supplied values or collect them through the temporary desktop GUI."""
    if state:
        output = normalize_user_input(state)
        log("초기 State의 입력값을 검증하여 사용합니다. GUI를 건너뜁니다.")
        return output

    log("사용자 입력 창을 표시합니다.")

    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    result: UserInputAgentOutput | None = None

    root = tk.Tk()
    root.title("Game Agent - 입력")
    root.resizable(False, False)

    frame = ttk.Frame(root, padding=20)
    frame.grid(row=0, column=0)

    ttk.Label(frame, text="이미지 스타일").grid(row=0, column=0, sticky="w", padx=5, pady=8)
    image_style_var = tk.StringVar(value=IMAGE_STYLE_OPTIONS[0])
    image_style_box = ttk.Combobox(
        frame,
        textvariable=image_style_var,
        state="readonly",
        width=24,
        values=IMAGE_STYLE_OPTIONS,
    )
    image_style_box.grid(row=0, column=1, padx=5, pady=8)

    ttk.Label(frame, text="분위기 스타일").grid(row=1, column=0, sticky="w", padx=5, pady=8)
    mood_style_var = tk.StringVar(value=MOOD_STYLE_OPTIONS[0])
    ttk.Combobox(
        frame,
        textvariable=mood_style_var,
        state="readonly",
        width=24,
        values=MOOD_STYLE_OPTIONS,
    ).grid(row=1, column=1, padx=5, pady=8)

    ttk.Label(frame, text="게임 장르").grid(row=2, column=0, sticky="w", padx=5, pady=8)
    genre_var = tk.StringVar(value=GENRE_OPTIONS[0])
    ttk.Combobox(
        frame,
        textvariable=genre_var,
        state="readonly",
        width=24,
        values=GENRE_OPTIONS,
    ).grid(row=2, column=1, padx=5, pady=8)

    ttk.Label(frame, text="시점").grid(row=3, column=0, sticky="w", padx=5, pady=8)
    viewpoint_var = tk.StringVar(value=VIEWPOINT_OPTIONS[0])
    ttk.Combobox(
        frame,
        textvariable=viewpoint_var,
        state="readonly",
        width=24,
        values=VIEWPOINT_OPTIONS,
    ).grid(row=3, column=1, padx=5, pady=8)

    ttk.Label(frame, text="조건").grid(row=4, column=0, sticky="w", padx=5, pady=8)
    condition_var = tk.StringVar(value="공격과 8방향 이동이 가능한 게임")
    ttk.Entry(frame, textvariable=condition_var, width=27).grid(row=4, column=1, padx=5, pady=8)

    custom_image_var = tk.StringVar()
    selected_file_var = tk.StringVar(value="선택된 파일 없음")

    def choose_custom_image() -> None:
        selected = filedialog.askopenfilename(filetypes=[("Image files", "*.png *.jpg *.jpeg")])
        if selected:
            custom_image_var.set(selected)
            selected_file_var.set(selected)

    ttk.Label(frame, text="Custom 이미지").grid(row=5, column=0, sticky="w", padx=5, pady=8)
    custom_image_button = ttk.Button(
        frame,
        text="PNG/JPG 선택",
        command=choose_custom_image,
    )
    custom_image_button.grid(row=5, column=1, sticky="ew", padx=5, pady=8)
    ttk.Label(frame, textvariable=selected_file_var, width=27).grid(
        row=6, column=1, sticky="w", padx=5
    )

    def update_custom_image_state(*_args: object) -> None:
        is_custom = image_style_var.get() == "Custom"
        custom_image_button.configure(state="normal" if is_custom else "disabled")
        if not is_custom:
            custom_image_var.set("")
            selected_file_var.set("선택된 파일 없음")

    image_style_box.bind("<<ComboboxSelected>>", update_custom_image_state)
    update_custom_image_state()

    def submit() -> None:
        nonlocal result
        candidate: dict[str, object] = {
            "image_style": image_style_var.get(),
            "mood_style": mood_style_var.get(),
            "genre": genre_var.get(),
            "viewpoint": viewpoint_var.get(),
            "condition": condition_var.get(),
        }
        if custom_image_var.get():
            candidate["custom_image_path"] = custom_image_var.get()

        try:
            result = normalize_user_input(candidate)
        except ValueError as error:
            messagebox.showerror("입력 확인", str(error), parent=root)
            return
        root.destroy()

    def cancel() -> None:
        root.destroy()

    ttk.Button(frame, text="START", command=submit).grid(
        row=7,
        column=0,
        columnspan=2,
        sticky="ew",
        padx=5,
        pady=(15, 5),
    )

    root.protocol("WM_DELETE_WINDOW", cancel)
    root.mainloop()

    if result is None:
        raise RuntimeError("User input was cancelled")

    log(
        "입력 완료 "
        f"(스타일={result['image_style']}, "
        f"분위기={result['mood_style']}, "
        f"장르={result['genre']}, "
        f"시점={result['viewpoint']}, "
        f"조건={result['condition']})"
    )
    return result

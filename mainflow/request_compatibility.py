"""Reject explicit contradictions between the selected genre and request text."""

from __future__ import annotations

import re

from mainflow.contracts import GameGenre

GENRE_MARKERS: dict[GameGenre, tuple[str, ...]] = {
    "플랫포머": (r"플랫포머\s*(?:게임)?", r"platformer\s*(?:game)?"),
    "타워 디펜스": (r"타워\s*디펜스\s*(?:게임)?", r"tower\s*defen[cs]e\s*(?:game)?"),
    "카드": (r"카드\s*(?:배틀|덱|게임)", r"(?:card|deckbuilding)\s*game"),
    "비주얼 노벨": (r"비주얼\s*노벨", r"visual\s*novel"),
    "육성 시뮬레이션": (r"육성\s*시뮬레이션", r"raising\s*simulation"),
    "뱀서류": (
        r"뱀서류",
        r"뱀파이어\s*서바이(?:버|벌)",
        r"vampire\s*survivors?\s*(?:like)?",
        r"survivors?[- ]?like",
    ),
}


def validate_genre_condition_compatibility(genre: GameGenre, condition: str) -> None:
    """Raise when the condition explicitly identifies itself as another supported genre."""

    conflicts = [
        candidate
        for candidate, markers in GENRE_MARKERS.items()
        if candidate != genre
        and any(re.search(marker, condition, flags=re.IGNORECASE) for marker in markers)
    ]
    if conflicts:
        names = ", ".join(conflicts)
        raise ValueError(
            f"선택한 장르 '{genre}'와 Condition에 명시된 장르 '{names}'가 충돌합니다. "
            "장르 선택을 바꾸거나 Condition의 장르 표현을 수정한 뒤 다시 실행하세요."
        )

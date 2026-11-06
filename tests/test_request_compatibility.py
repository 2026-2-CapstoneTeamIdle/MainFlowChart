from __future__ import annotations

import pytest

from mainflow.request_compatibility import validate_genre_condition_compatibility


def test_rejects_explicit_platformer_condition_for_survivor_genre() -> None:
    with pytest.raises(ValueError, match="장르 '뱀서류'.*'플랫포머'"):
        validate_genre_condition_compatibility(
            "뱀서류",
            "붕괴하는 탑을 탈출하는 2D 사이드뷰 액션 플랫포머 게임",
        )


def test_allows_features_shared_by_multiple_genres() -> None:
    validate_genre_condition_compatibility(
        "뱀서류",
        "넓은 맵에서 적을 피하고 경험치를 모아 성장하는 게임",
    )


def test_allows_explicit_selected_genre() -> None:
    validate_genre_condition_compatibility(
        "뱀서류",
        "플레이어 주변 무기가 자동 공격하는 뱀서류 게임",
    )

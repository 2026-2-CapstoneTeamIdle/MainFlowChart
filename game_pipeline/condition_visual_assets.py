"""Carry request-specific weapon details into the first image asset request."""

from __future__ import annotations

import re
from copy import deepcopy

from mainflow.contracts import GameSpec


def with_condition_visual_assets(game_spec: GameSpec, condition: str) -> GameSpec:
    if game_spec["genre"] != "SurvivorLike":
        return game_spec

    sentences = [part.strip() for part in re.split(r"[.!?。\n]+", condition) if part.strip()]
    weapon_words = (
        "검",
        "칼",
        "도끼",
        "창",
        "낫",
        "활",
        "총",
        "지팡이",
        "sword",
        "axe",
        "spear",
        "bow",
        "gun",
    )
    weapon_sentence = next(
        (
            sentence
            for sentence in sentences
            if any(word in sentence.lower() for word in weapon_words)
            and not any(
                negation in sentence for negation in ("안 된다", "하지 않는다", "없다", "제외")
            )
        ),
        "",
    )
    if not weapon_sentence:
        return game_spec

    result = deepcopy(game_spec)
    for asset in result["asset_requirements"]:
        if asset["asset_id"] != "primary_attack_visual":
            continue
        asset["description"] = (
            f"{weapon_sentence}. 이 공격 수단 한 개만 단독으로 그린 투명 배경 게임 스프라이트. "
            "플레이어, 마법사, 적, 얼굴, 몸통, 글자, 배경을 그리지 않는다."
        )
        if ("회전" in weapon_sentence or "orbit" in weapon_sentence.lower()) and any(
            word in weapon_sentence.lower() for word in ("검", "칼", "sword")
        ):
            asset["purpose"] = "플레이어 주변을 회전하는 검 무기"
            asset["description"] += (
                " 손잡이와 칼날이 보이는 검 한 자루이며 투사체나 인물 그림이 아니다."
            )
        break
    return result

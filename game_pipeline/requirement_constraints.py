"""Preserve explicit user exclusions while requirements pass through multiple planners."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from mainflow.contracts import FeatureRequirement

_PLAYER_ATTACK_EXCLUSIONS = (
    re.compile(r"플레이어.{0,100}(?:공격|적.{0,20}처치).{0,40}(?:없|않|못|불가)"),
    re.compile(r"(?:공격능력|공격수단).{0,30}(?:없|않|못|불가)"),
    re.compile(r"(?:적을)?직접처치.{0,40}(?:하지않|못|대신|보다피)"),
    re.compile(r"player.{0,80}(?:cannot|can't|doesnot|doesn't|without|no).{0,30}attack"),
    re.compile(r"(?:no|without).{0,30}playerattack"),
)

_NEGATIVE_WORDS = (
    "없",
    "않",
    "못",
    "불가",
    "cannot",
    "can't",
    "doesnot",
    "without",
    "noattack",
)
_PLAYER_ATTACK_NAMES = {
    "공격",
    "자동공격",
    "8방향공격",
    "playerattack",
    "primaryattack",
    "autoattack",
}
_PLAYER_ATTACK_POSITIVE = re.compile(
    r"(?:플레이어|캐릭터|주인공)(?:가|는|이)?(?:직접|스스로)?"
    r"(?:적|목표|대상)[^.!?\r\n]{0,12}(?:공격|타격|피해|처치)"
)


def explicit_exclusions(condition: str) -> set[str]:
    """Return capabilities that the user explicitly prohibited."""

    normalized = _normalize(condition)
    exclusions: set[str] = set()
    if any(pattern.search(normalized) for pattern in _PLAYER_ATTACK_EXCLUSIONS):
        exclusions.add("player_attack")
    return exclusions


def feature_conflict_reason(
    feature: Mapping[str, Any],
    condition: str,
) -> str | None:
    """Explain why a positive feature contradicts an explicit request exclusion."""

    if "player_attack" not in explicit_exclusions(condition):
        return None
    name = _normalize(str(feature.get("name", feature.get("feature_id", ""))))
    description = _normalize(str(feature.get("description", "")))
    candidate = name + description
    # Keep the negative requirement itself; reject only its positive opposite.
    if any(word in candidate for word in _NEGATIVE_WORDS):
        return None
    player_attack = (
        name in _PLAYER_ATTACK_NAMES
        or re.search(r"플레이어(?:가|는|이).{0,30}(?:적|목표).{0,20}(?:공격|피해|처치)", candidate)
        is not None
        or re.search(r"player.{0,40}(?:attack|damage|kill)", candidate) is not None
    )
    if player_attack:
        return "explicit user constraint disables player attack"
    return None


def filter_conflicting_features(
    features: Iterable[FeatureRequirement],
    condition: str,
) -> tuple[list[FeatureRequirement], list[dict[str, str]]]:
    """Remove positive requirements contradicted by an explicit user constraint."""

    accepted: list[FeatureRequirement] = []
    rejected: list[dict[str, str]] = []
    for feature in features:
        reason = feature_conflict_reason(feature, condition)
        if reason is None:
            accepted.append(feature)
            continue
        rejected.append(
            {
                "feature_id": feature["feature_id"],
                "name": feature["name"],
                "description": feature["description"],
                "reason": reason,
            }
        )
    return accepted, rejected


def filter_genre_conflicting_features(
    features: Iterable[FeatureRequirement],
    condition: str,
    genre: str,
) -> tuple[list[FeatureRequirement], list[dict[str, str]]]:
    """Remove inferred player-attack requirements from genres without player attacks.

    Condition/genre LLMs often see words such as ``타워가 ... 공격`` and emit the
    generic feature ``공격`` with the description ``플레이어가 ... 공격``.  In a
    tower-defense request the tower, not the player, owns that action unless the
    user explicitly assigns an attack to the player.
    """

    if genre != "타워 디펜스" or _PLAYER_ATTACK_POSITIVE.search(_normalize(condition)):
        return list(features), []
    accepted: list[FeatureRequirement] = []
    rejected: list[dict[str, str]] = []
    for feature in features:
        name = _normalize(str(feature.get("name", "")))
        description = _normalize(str(feature.get("description", "")))
        candidate = name + description
        if name in _PLAYER_ATTACK_NAMES or "플레이어가적또는목표를공격" in candidate:
            rejected.append(
                {
                    "feature_id": feature["feature_id"],
                    "name": feature["name"],
                    "description": feature["description"],
                    "reason": "tower-defense attack belongs to towers unless player attack is explicit",
                }
            )
        else:
            accepted.append(feature)
    return accepted, rejected


def _normalize(value: str) -> str:
    return re.sub(r"[^0-9a-zA-Z가-힣]+", "", value).casefold()

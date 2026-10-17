"""Turn the user's request and the sound asset request into concrete sound plans.

Each requested asset becomes one ``SoundPlan``: whether it is background music
or a sound effect, how long it should be, whether it must loop, and an English
generation prompt built from the user's mood, genre, image style, viewpoint and
condition. Asset IDs are opaque (ContractRule), so the kind is decided from the
``purpose`` and ``description`` text only.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal, cast

from mainflow.contracts import (
    AssetGenerationItem,
    AssetGenerationRequest,
    ParsedRequest,
    SoundAssetKind,
    SoundGenerationSpec,
)
from mainflow.keywords import has_keyword

SoundKind = SoundAssetKind
SfxCategory = Literal["ui", "impact", "explosion", "ambience", "action"]

BGM_KEYWORDS = ("배경음악", "배경 음악", "bgm", "음악", "music", "theme", "테마", "ost")
SFX_CATEGORY_KEYWORDS: tuple[tuple[SfxCategory, tuple[str, ...]], ...] = (
    ("ambience", ("환경음", "앰비언스", "ambience", "ambient", "바람", "빗소리", "물소리", "숲")),
    ("explosion", ("폭발", "스킬", "explosion", "blast", "마법")),
    ("ui", ("ui", "선택", "클릭", "메뉴", "버튼", "결정", "확인", "click", "menu")),
    ("impact", ("공격", "피격", "타격", "발사", "명중", "hit", "attack", "slash", "shoot")),
)
NO_LOOP_KEYWORDS = ("엔딩", "ending", "승리", "패배", "game over", "게임오버", "클리어")
LOOP_KEYWORDS = ("반복", "루프", "loop")

MOOD_DESCRIPTORS = {
    "Cyberpunk": "dark synthwave, neon-lit electronic, pulsing bass",
    "Medieval": "medieval folk instruments, lute and hand drums",
    "Modern": "modern clean electronic pop",
    "Fantasy": "orchestral fantasy, magical and adventurous",
    "Horror": "eerie dark ambient, dissonant and tense",
    "Cozy": "warm gentle acoustic, cozy and relaxed",
}
GENRE_DESCRIPTORS = {
    "Platformer": ("platformer", "bouncy and upbeat"),
    "TowerDefense": ("tower defense", "steady and strategic"),
    "CardGame": ("card game", "thoughtful and light"),
    "SurvivorLike": ("survivor-like action", "energetic and driving"),
    "VisualNovel": ("visual novel", "emotional and gentle"),
    "RaisingSimulation": ("raising simulation", "cheerful everyday"),
}
STYLE_HINTS = {
    "Pixel Art": "retro 8-bit chiptune flavor",
    "Low Poly": "simple stylized retro-3D game feel",
    "Anime": "anime game soundtrack feel",
    "Cartoon": "playful cartoon feel",
    "Realistic": "realistic cinematic production",
    "Custom": "",
}
SFX_LABELS: dict[SfxCategory, str] = {
    "ui": "User-interface",
    "impact": "Attack/impact",
    "explosion": "Explosion/skill",
    "ambience": "Looping ambience",
    "action": "Gameplay action",
}
SFX_DURATIONS: dict[SfxCategory, float] = {
    "ui": 0.5,  # ElevenLabs Sound Effects minimum
    "impact": 0.7,
    "explosion": 2.0,
    "ambience": 10.0,
    "action": 0.9,
}


@dataclass(frozen=True)
class SoundPlan:
    asset_id: str
    name: str
    file_stem: str  # extension is chosen by the provider's actual output format
    kind: SoundKind
    category: str
    prompt: str
    duration_seconds: float
    loop: bool
    mood_style: str
    genre: str
    required: bool
    unity_binding_key: str = ""
    mixer_group: str = "SFX"


def bgm_seconds() -> float:
    # Music API accepts 3-600 s; clamping here keeps the plan equal to what is requested.
    return min(max(float(os.environ.get("SOUND_BGM_SECONDS", "30")), 3.0), 600.0)


def _text(item: AssetGenerationItem) -> str:
    return f"{item['purpose']} {item['description']}".lower()


def classify(item: AssetGenerationItem) -> tuple[SoundKind, str]:
    text = _text(item)
    if has_keyword(text, BGM_KEYWORDS):
        return "bgm", "bgm"
    for category, keywords in SFX_CATEGORY_KEYWORDS:
        if has_keyword(text, keywords):
            return "sfx", category
    return "sfx", "action"


def _file_stem(item: AssetGenerationItem) -> str:
    return item["suggested_filename"].rsplit(".", 1)[0] or item["asset_id"]


def plan_sound_assets(request: AssetGenerationRequest, parsed: ParsedRequest) -> list[SoundPlan]:
    genre_name, genre_energy = GENRE_DESCRIPTORS.get(request["genre"], ("indie", "balanced"))
    mood = MOOD_DESCRIPTORS.get(request["mood_style"], request["mood_style"])
    style = STYLE_HINTS.get(request["image_style"], "")
    condition = parsed["condition"].strip()

    plans: list[SoundPlan] = []
    for item in request["assets"]:
        inferred_kind, category = classify(item)
        text = _text(item)
        raw_spec = item.get("generation_spec")
        generation_spec = (
            cast(SoundGenerationSpec, raw_spec) if isinstance(raw_spec, dict) else None
        )
        kind = generation_spec["kind"] if generation_spec else inferred_kind
        if kind in {"ui", "ambience"}:
            category = kind
        elif kind == "voice":
            category = "action"
        if kind == "bgm":
            loop = (
                generation_spec["loop"]
                if generation_spec
                else not has_keyword(text, NO_LOOP_KEYWORDS)
            )
            duration = (
                generation_spec["target_duration_seconds"] if generation_spec else bgm_seconds()
            )
            parts = [
                (
                    f"Instrumental {'seamlessly looping ' if loop else ''}background music "
                    f"for a {genre_name} game titled '{request['game_title']}'"
                ),
                f"Mood: {mood}",
                f"Energy: {genre_energy}",
                style,
                f"Scene: {item['purpose']} - {item['description']}",
                f"Gameplay: {condition}",
                "No vocals, no speech",
            ]
        else:
            loop = (
                generation_spec["loop"]
                if generation_spec
                else category == "ambience" or has_keyword(text, LOOP_KEYWORDS)
            )
            duration = (
                generation_spec["target_duration_seconds"]
                if generation_spec
                else SFX_DURATIONS[category]  # type: ignore[index]
            )
            parts = [
                (
                    f"{SFX_LABELS[category]} sound effect for a {genre_name} game "  # type: ignore[index]
                    f"({request['viewpoint']} view)"
                ),
                f"Event: {item['purpose']} - {item['description']}",
                f"Sound palette: {mood}",
                style,
                "Single clean sound, no music, no voice"
                if category != "ambience"
                else "No music, no voice",
            ]
        plans.append(
            SoundPlan(
                asset_id=item["asset_id"],
                name=item["purpose"],
                file_stem=_file_stem(item),
                kind=kind,
                category=category,
                prompt=". ".join(part for part in parts if part) + ".",
                duration_seconds=duration,
                loop=loop,
                mood_style=request["mood_style"],
                genre=request["genre"],
                required=item["required"],
                unity_binding_key=item.get("unity_binding_key", ""),
                mixer_group=generation_spec["mixer_group"] if generation_spec else "SFX",
            )
        )
    return plans

"""Deterministic image and sound generation requirements for agent handoff."""

from __future__ import annotations

import re

from mainflow.contracts import (
    ImageAssetKind,
    ImageGenerationSpec,
    SoundAssetKind,
    SoundGenerationSpec,
)

IMAGE_KIND_KEYWORDS: tuple[tuple[ImageAssetKind, tuple[str, ...]], ...] = (
    ("tileset", ("타일", "tile")),
    ("ui", ("ui", "테두리", "프레임", "frame", "아이콘", "icon", "버튼", "button")),
    ("illustration", ("일러스트", "illustration")),
    ("portrait", ("초상화", "portrait")),
    ("background", ("배경", "background", "맵", "map", "스테이지", "stage")),
)

IMAGE_SIZES: dict[ImageAssetKind, tuple[int, int]] = {
    "sprite": (64, 64),
    "portrait": (256, 384),
    "ui": (128, 128),
    "tileset": (128, 128),
    "illustration": (256, 256),
    "background": (512, 384),
}

# On-screen size (width, height in Unity units) of scene objects built by
# PrefabSceneAssembler.cs. Sprites for these objects are generated with the same
# aspect ratio, so the art fills the object instead of shrinking into a square.
# Keep in sync with the sizes passed to CreateSpriteObject in PrefabSceneAssembler.cs.
OBJECT_FOOTPRINT_UNITS: dict[str, tuple[float, float]] = {
    "platformer_player": (0.8, 1.2),
    "platformer_enemy": (0.8, 0.8),
    "platformer_hazard": (0.9, 0.35),
    "platformer_collectible": (0.45, 0.45),
    "platformer_checkpoint": (0.45, 1.8),
    "platformer_goal": (0.8, 2.0),
}
# Pixel density of footprint-sized sprites (two pixels per tileset pixel).
OBJECT_PIXELS_PER_UNIT = 64
MINIMUM_OBJECT_SPRITE_PIXELS = 24
# Objects that stand on the ground. Their art is anchored to the bottom of the canvas
# (no gap under the feet) and Unity fits it to the object height, not its width.
GROUNDED_OBJECT_IDS: frozenset[str] = frozenset(
    {
        "platformer_player",
        "platformer_enemy",
        "platformer_hazard",
        "platformer_checkpoint",
        "platformer_goal",
    }
)
# Characters and props may be drawn wider than their collider, as in most games, so
# their canvas leaves this much horizontal room. Hazards stay exact so the visible
# spikes match the area that deals damage. Keep in sync with GeneratedAssetBinder.cs.
OBJECT_ART_WIDTH_ROOM: dict[str, float] = {
    "platformer_player": 1.4,
    "platformer_enemy": 1.4,
    "platformer_checkpoint": 1.4,
    "platformer_goal": 1.4,
}


def is_grounded_object(asset_id: str | None) -> bool:
    return (asset_id or "") in GROUNDED_OBJECT_IDS


def _footprint_pixels(asset_id: str | None) -> tuple[int, int] | None:
    footprint = OBJECT_FOOTPRINT_UNITS.get(asset_id or "")
    if footprint is None:
        return None
    width_units, height_units = footprint
    width_units *= OBJECT_ART_WIDTH_ROOM.get(asset_id or "", 1.0)
    width, height = (
        max(MINIMUM_OBJECT_SPRITE_PIXELS, 2 * round(units * OBJECT_PIXELS_PER_UNIT / 2))
        for units in (width_units, height_units)
    )
    return width, height


SOUND_KIND_KEYWORDS: tuple[tuple[SoundAssetKind, tuple[str, ...]], ...] = (
    ("bgm", ("bgm", "배경음악", "음악", "music", "theme")),
    ("ambience", ("환경음", "ambience", "ambient")),
    ("voice", ("음성", "대사", "voice", "dialogue")),
    ("ui", ("ui", "버튼", "button", "menu")),
)


# Runtime cue IDs raised through GameAudioCues in the Unity template; keep both in sync.
# Order matters: more specific events come before generic ones ("피격" before "공격").
# Ambiguous words are phrase-only: "피해" alone also means "avoid", "사망" alone also fits enemies.
SOUND_CUE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "tower_built",
        ("tower_built", "tower construction succeeds", "타워 건설 성공", "건설 성공"),
    ),
    (
        "tower_upgraded",
        ("tower_upgraded", "tower upgrade succeeds", "타워 업그레이드 성공"),
    ),
    (
        "enemy_defeated",
        ("enemy_defeated", "enemy health reaches zero", "적 처치", "적 격파"),
    ),
    (
        "base_damaged",
        ("base_damaged", "enemy reaches base", "기지 피해", "기지 도달"),
    ),
    (
        "wave_started",
        ("wave_started", "preparation expires", "웨이브 시작"),
    ),
    (
        "boss_arrived",
        ("boss_arrived", "boss wave begins", "보스 등장", "보스 웨이브 시작"),
    ),
    ("boss_spawn", ("boss_spawn",)),
    (
        "game_over",
        ("패배", "게임오버", "게임 오버", "플레이어 사망", "game over", "defeat", "player death"),
    ),
    (
        "game_clear",
        ("승리", "클리어", "엔딩", "victory", "stage clear", "game clear", "level clear", "ending"),
    ),
    ("level_up", ("level_up", "레벨업", "레벨 업", "level up")),
    ("checkpoint", ("체크포인트", "checkpoint")),
    ("jump", ("점프", "jump")),
    ("card_play", ("카드", "card")),
    (
        "pickup",
        ("xp_pickup", "획득", "수집", "아이템", "코인", "경험치", "pickup", "collect", "coin"),
    ),
    ("enemy_hit", ("적 피격", "적이 맞", "적이 피해", "enemy hit", "enemy hurt", "enemy damage")),
    ("player_hit", ("피격", "피해를 입", "피해 입", "데미지", "hit", "damage", "hurt")),
    ("attack", ("공격", "발사", "타격", "사격", "attack", "shoot", "fire")),
    ("activity", ("행동", "훈련", "활동", "activity", "train")),
    ("ui", ("ui", "선택", "클릭", "메뉴", "버튼", "결정", "확인", "click", "menu", "button")),
)
SCENE_START_CUE = "scene_start"


def _has_keyword(text: str, keyword: str) -> bool:
    # English matches whole words only ("ui" must not match "guitar"/"build", "clear" not "clear하고").
    if keyword.isascii():
        return re.search(rf"\b{re.escape(keyword)}\b", text) is not None
    return keyword in text


def classify_sound_cue(purpose: str, description: str, kind: str) -> str:
    """Pick the gameplay event that plays a sound; empty means no matching event."""
    text = f"{purpose} {description}".lower()
    cue = next(
        (
            cue
            for cue, keywords in SOUND_CUE_KEYWORDS
            if any(_has_keyword(text, k) for k in keywords)
        ),
        "",
    )
    if kind in {"bgm", "ambience"}:
        # Music only switches on stage end; any other music starts with the scene.
        return cue if cue in {"game_clear", "game_over"} else SCENE_START_CUE
    return cue or ("ui" if kind == "ui" else "")


def classify_image_kind(purpose: str, description: str) -> ImageAssetKind:
    text = f"{purpose} {description}".lower()
    for kind, keywords in IMAGE_KIND_KEYWORDS:
        if any(keyword in text for keyword in keywords):
            return kind
    return "sprite"


def build_image_generation_spec(
    purpose: str,
    description: str,
    asset_id: str | None = None,
) -> ImageGenerationSpec:
    kind = classify_image_kind(purpose, description)
    width, height = IMAGE_SIZES[kind]
    pixels_per_unit = 32
    footprint = _footprint_pixels(asset_id) if kind == "sprite" else None
    if footprint is not None:
        width, height = footprint
        pixels_per_unit = OBJECT_PIXELS_PER_UNIT
    spec: ImageGenerationSpec = {
        "kind": kind,
        "width": width,
        "height": height,
        "transparent": kind in {"sprite", "portrait", "ui"},
        "sprite_mode": "multiple" if kind == "tileset" else "single",
        "pixels_per_unit": pixels_per_unit,
    }
    if kind == "tileset":
        # Unity slices the 128x128 sheet into sixteen 32x32 tiles.
        spec.update({"tile_width": 32, "tile_height": 32, "columns": 4, "rows": 4})
    return spec


def classify_sound_kind(purpose: str, description: str) -> SoundAssetKind:
    text = f"{purpose} {description}".lower()
    for kind, keywords in SOUND_KIND_KEYWORDS:
        if any(_has_keyword(text, keyword) for keyword in keywords):
            return kind
    return "sfx"


def build_sound_generation_spec(purpose: str, description: str) -> SoundGenerationSpec:
    kind = classify_sound_kind(purpose, description)
    if kind == "bgm":
        duration, loop, channels, load_type, mixer = (
            90.0,
            True,
            "stereo",
            "streaming",
            "Music",
        )
    elif kind == "ambience":
        duration, loop, channels, load_type, mixer = (
            60.0,
            True,
            "stereo",
            "streaming",
            "Ambience",
        )
    elif kind == "voice":
        duration, loop, channels, load_type, mixer = (
            5.0,
            False,
            "mono",
            "compressed_in_memory",
            "Voice",
        )
    elif kind == "ui":
        duration, loop, channels, load_type, mixer = (
            0.5,
            False,
            "mono",
            "decompress_on_load",
            "UI",
        )
    else:
        duration, loop, channels, load_type, mixer = (
            1.0,
            False,
            "mono",
            "decompress_on_load",
            "SFX",
        )
    return {
        "kind": kind,
        "audio_cue": classify_sound_cue(purpose, description, kind),
        "target_duration_seconds": duration,
        "loop": loop,
        "channels": channels,  # type: ignore[typeddict-item]
        "sample_rate_hz": 44100,
        "unity_load_type": load_type,  # type: ignore[typeddict-item]
        "mixer_group": mixer,
        "spatial_blend": 0.0,
    }

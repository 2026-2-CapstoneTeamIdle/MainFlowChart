"""Deterministic image and sound generation requirements for agent handoff."""

from __future__ import annotations

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

SOUND_KIND_KEYWORDS: tuple[tuple[SoundAssetKind, tuple[str, ...]], ...] = (
    ("bgm", ("bgm", "배경음악", "음악", "music", "theme")),
    ("ambience", ("환경음", "ambience", "ambient")),
    ("voice", ("음성", "대사", "voice", "dialogue")),
    ("ui", ("ui", "버튼", "button", "menu")),
)


def classify_image_kind(purpose: str, description: str) -> ImageAssetKind:
    text = f"{purpose} {description}".lower()
    for kind, keywords in IMAGE_KIND_KEYWORDS:
        if any(keyword in text for keyword in keywords):
            return kind
    return "sprite"


def build_image_generation_spec(purpose: str, description: str) -> ImageGenerationSpec:
    kind = classify_image_kind(purpose, description)
    width, height = IMAGE_SIZES[kind]
    spec: ImageGenerationSpec = {
        "kind": kind,
        "width": width,
        "height": height,
        "transparent": kind in {"sprite", "portrait", "ui"},
        "sprite_mode": "multiple" if kind == "tileset" else "single",
        "pixels_per_unit": 32,
    }
    if kind == "tileset":
        # Unity slices the 128x128 sheet into sixteen 32x32 tiles.
        spec.update({"tile_width": 32, "tile_height": 32, "columns": 4, "rows": 4})
    return spec


def classify_sound_kind(purpose: str, description: str) -> SoundAssetKind:
    text = f"{purpose} {description}".lower()
    for kind, keywords in SOUND_KIND_KEYWORDS:
        if any(keyword in text for keyword in keywords):
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
        "target_duration_seconds": duration,
        "loop": loop,
        "channels": channels,  # type: ignore[typeddict-item]
        "sample_rate_hz": 44100,
        "unity_load_type": load_type,  # type: ignore[typeddict-item]
        "mixer_group": mixer,
        "spatial_blend": 0.0,
    }

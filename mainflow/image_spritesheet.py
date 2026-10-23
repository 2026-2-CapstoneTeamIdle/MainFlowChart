"""Build animation sprite sheets (idle, run, jump, ...) from one base sprite.

Frames are made by transforming the generated base sprite (bounce, squash and
stretch, lean) instead of asking a generator for every pose.  This works with
every image backend, keeps the character identical across frames and costs no
extra API calls.  The sheet has one row per animation and comes with a JSON
metadata file that Unity can use to slice frames and build clips.
"""

from __future__ import annotations

import io
import os
from dataclasses import dataclass
from typing import Any

from PIL import Image

from mainflow.contracts import CONTRACT_VERSION, GenreProfile, ImageStyle
from mainflow.image_backends import PIXEL_ART_COLORS, pixelate_palette
from mainflow.image_generation import ImageAssetPlan

SPRITE_SHEETS_ENVIRONMENT_KEY = "MAINFLOW_IMAGE_SPRITE_SHEETS"
SHEET_MEDIA_TYPE = "image/png"
# Frames keep the character's feet on this row so clips do not jitter.
PIVOT = (0.5, 0.0)
# The character is shrunk to this share of the frame height, leaving headroom
# for jump and stretch frames.
CONTENT_HEIGHT_SHARE = 0.8
# validate_sheet() accepts per-frame character heights within this range of
# the first frame of the first animation.
FRAME_HEIGHT_TOLERANCE = (0.7, 1.35)


@dataclass(frozen=True)
class Keyframe:
    """One frame as a transform of the base sprite.

    ``dx``/``dy`` are offsets as a share of the frame size (``dy`` < 0 moves up),
    ``sx``/``sy`` scale the character around its feet, ``angle`` leans it in
    degrees (negative leans forward/right) and ``flash`` brightens it.
    """

    dx: float = 0.0
    dy: float = 0.0
    sx: float = 1.0
    sy: float = 1.0
    angle: float = 0.0
    flash: float = 0.0


@dataclass(frozen=True)
class AnimationSpec:
    name: str
    fps: int
    loop: bool
    keyframes: tuple[Keyframe, ...]


IDLE = AnimationSpec(
    "idle",
    fps=6,
    loop=True,
    keyframes=(
        Keyframe(),
        Keyframe(sx=0.99, sy=1.02),
        Keyframe(sx=0.98, sy=1.04),
        Keyframe(sx=0.99, sy=1.02),
    ),
)
RUN = AnimationSpec(
    "run",
    fps=12,
    loop=True,
    keyframes=(
        Keyframe(sx=1.04, sy=0.95, angle=-6),
        Keyframe(dy=-0.04, angle=-8),
        Keyframe(dy=-0.06, sx=0.97, sy=1.04, angle=-8),
        Keyframe(sx=1.04, sy=0.95, angle=-6),
        Keyframe(dy=-0.04, angle=-8),
        Keyframe(dy=-0.06, sx=0.97, sy=1.04, angle=-8),
    ),
)
JUMP = AnimationSpec(
    "jump",
    fps=10,
    loop=False,
    keyframes=(
        Keyframe(sx=1.1, sy=0.86),  # crouch before take-off
        Keyframe(dy=-0.1, sx=0.9, sy=1.12),  # airborne stretch
        Keyframe(sx=1.12, sy=0.84),  # landing squash
    ),
)
WALK = AnimationSpec(
    "walk",
    fps=10,
    loop=True,
    keyframes=(
        Keyframe(sx=1.02, sy=0.97),
        Keyframe(dy=-0.02, angle=-3),
        Keyframe(dy=-0.03),
        Keyframe(sx=1.02, sy=0.97),
        Keyframe(dy=-0.02, angle=3),
        Keyframe(dy=-0.03),
    ),
)
HIT = AnimationSpec(
    "hit",
    fps=12,
    loop=False,
    keyframes=(
        Keyframe(dx=-0.06, angle=8, flash=0.8),
        Keyframe(dx=-0.03, angle=4, flash=0.3),
        Keyframe(),
    ),
)

# Default animation sets per genre until the asset request carries an
# explicit animation list.
# TODO: read the list from the asset request once the contract adds it.
GENRE_ANIMATIONS: dict[GenreProfile, tuple[AnimationSpec, ...]] = {
    "Platformer": (IDLE, RUN, JUMP),
    "SurvivorLike": (IDLE, WALK, HIT),
    "TowerDefense": (WALK, HIT),
}
# Only character-like sprites are animated; projectiles, towers and items are
# left as single images.
ANIMATED_PURPOSE_KEYWORDS = ("플레이어", "player", "캐릭터", "character", "적", "enemy")


def sprite_sheets_enabled() -> bool:
    value = os.environ.get(SPRITE_SHEETS_ENVIRONMENT_KEY, "on").strip().lower()
    return value not in ("off", "false", "0", "no")


def animations_for(plan: ImageAssetPlan, genre: GenreProfile) -> tuple[AnimationSpec, ...]:
    """Return the animations to build for a planned asset, or ``()``."""

    if plan.kind != "sprite":
        return ()
    text = f"{plan.purpose} {plan.description}".lower()
    if not any(keyword in text for keyword in ANIMATED_PURPOSE_KEYWORDS):
        return ()
    return GENRE_ANIMATIONS.get(genre, ())


def sheet_filename(plan: ImageAssetPlan) -> str:
    return plan.filename.removesuffix(".png") + "_sheet.png"


def metadata_filename(plan: ImageAssetPlan) -> str:
    return plan.filename.removesuffix(".png") + "_sheet.json"


def build_sprite_sheet(
    base_png: bytes,
    plan: ImageAssetPlan,
    animations: tuple[AnimationSpec, ...],
    style: ImageStyle,
) -> tuple[bytes, dict[str, Any]]:
    """Return the sheet PNG and its metadata for ``animations``."""

    if not animations:
        raise ValueError("At least one animation is required for a sprite sheet")
    with Image.open(io.BytesIO(base_png)) as source:
        base = source.convert("RGBA")
    frame_width, frame_height = base.size
    character = _prepare_character(base)
    resample = Image.Resampling.NEAREST if style == "Pixel Art" else Image.Resampling.BICUBIC

    columns = max(len(animation.keyframes) for animation in animations)
    sheet = Image.new("RGBA", (frame_width * columns, frame_height * len(animations)))
    for row, animation in enumerate(animations):
        for column, keyframe in enumerate(animation.keyframes):
            frame = _render_frame(character, keyframe, frame_width, frame_height, resample)
            sheet.alpha_composite(frame, (column * frame_width, row * frame_height))

    if style == "Pixel Art":
        # One palette for the whole sheet so colors do not flicker between frames.
        sheet = pixelate_palette(sheet, PIXEL_ART_COLORS)

    output = io.BytesIO()
    sheet.save(output, format="PNG", optimize=True)
    metadata: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "asset_id": plan.asset_id,
        "unity_binding_key": plan.unity_binding_key,
        "frame_width": frame_width,
        "frame_height": frame_height,
        "columns": columns,
        "rows": len(animations),
        "pivot": list(PIVOT),
        "animations": {
            animation.name: {
                "row": row,
                "frames": len(animation.keyframes),
                "fps": animation.fps,
                "loop": animation.loop,
            }
            for row, animation in enumerate(animations)
        },
    }
    return output.getvalue(), metadata


def validate_sheet(content: bytes, metadata: dict[str, Any]) -> list[tuple[str, str]]:
    """Return ``(code, message)`` problems found in a sheet and its metadata."""

    with Image.open(io.BytesIO(content)) as source:
        sheet = source.convert("RGBA")
    frame_width = int(metadata["frame_width"])
    frame_height = int(metadata["frame_height"])
    expected = (frame_width * int(metadata["columns"]), frame_height * int(metadata["rows"]))
    if sheet.size != expected:
        return [
            (
                "image-sprite-sheet",
                f"시트 크기 {sheet.size[0]}x{sheet.size[1]}가 격자 {expected[0]}x{expected[1]}와 다릅니다.",
            )
        ]

    problems: list[tuple[str, str]] = []
    reference_height: int | None = None
    for name, animation in metadata["animations"].items():
        for index in range(int(animation["frames"])):
            left = index * frame_width
            top = int(animation["row"]) * frame_height
            frame = sheet.crop((left, top, left + frame_width, top + frame_height))
            bounding_box = frame.getchannel("A").getbbox()
            if bounding_box is None:
                problems.append(
                    ("image-sprite-sheet", f"{name} {index + 1}번 프레임이 비어 있습니다.")
                )
                continue
            height = bounding_box[3] - bounding_box[1]
            if reference_height is None:
                reference_height = height
                continue
            low, high = FRAME_HEIGHT_TOLERANCE
            if not low * reference_height <= height <= high * reference_height:
                problems.append(
                    (
                        "image-sprite-sheet",
                        f"{name} {index + 1}번 프레임의 캐릭터 높이({height}px)가 "
                        f"기준({reference_height}px)과 크게 다릅니다.",
                    )
                )
    return problems


def _prepare_character(base: Image.Image) -> Image.Image:
    """Crop the base sprite to its visible character and shrink it for headroom."""

    bounding_box = base.getchannel("A").getbbox()
    if bounding_box is None:
        raise ValueError("Base sprite has no visible pixels to animate")
    character = base.crop(bounding_box)
    limit = base.height * CONTENT_HEIGHT_SHARE
    if character.height > limit:
        scale = limit / character.height
        character = character.resize(
            (max(1, round(character.width * scale)), max(1, round(limit))),
            Image.Resampling.LANCZOS,
        )
    return character


def _render_frame(
    character: Image.Image,
    keyframe: Keyframe,
    frame_width: int,
    frame_height: int,
    resample: Image.Resampling,
) -> Image.Image:
    body = character.resize(
        (
            max(1, round(character.width * keyframe.sx)),
            max(1, round(character.height * keyframe.sy)),
        ),
        resample,
    )
    if keyframe.angle:
        body = body.rotate(keyframe.angle, resample=resample, expand=True)
        # Drop the transparent padding added by expand so the feet stay anchored.
        bounding_box = body.getchannel("A").getbbox()
        if bounding_box is not None:
            body = body.crop(bounding_box)
    if keyframe.flash:
        white = Image.new("RGBA", body.size, (255, 255, 255, 255))
        white.putalpha(body.getchannel("A"))
        body = Image.blend(body, white, keyframe.flash)

    frame = Image.new("RGBA", (frame_width, frame_height), (0, 0, 0, 0))
    # Anchor the feet (bottom centre) at the pivot, then apply the offsets.
    left = round((frame_width - body.width) / 2 + keyframe.dx * frame_width)
    top = round(frame_height - body.height + keyframe.dy * frame_height)
    top = max(0, top)  # never push the head out of the frame
    # The canvas is empty, so a plain paste copies pixels and alpha exactly and
    # clips anything a lean pushes past the frame edge.
    frame.paste(body, (left, top))
    return frame

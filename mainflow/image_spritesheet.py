"""Build animation sprite sheets (idle, run, jump, ...) for character sprites.

Two frame sources, chosen per animation:

- ``ai``: the generator draws one animation as a single strip, using the base
  sprite as its reference image.  The strip is split into frames, scaled to
  the base character's height, foot-aligned and locked to the base palette.
  Real poses (legs and arms moving) come from here.  Only generators with a
  ``generate_animation_strip`` method support it (currently ``openai``).
- ``transform``: frames are made from the base sprite with integer pixel
  operations only (bob, row-shift lean, row squash, leg stride), so pixel art
  never gets rotated or resampled.  Always available, no API cost, and the
  fallback whenever an ``ai`` strip cannot be used.

``MAINFLOW_IMAGE_SPRITE_SHEET_MODE`` selects ``auto`` (default: ``ai`` when the
generator supports it), ``ai`` or ``transform``.  The sheet has one row per
animation and comes with a JSON metadata file that Unity can use to slice
frames and build clips.
"""

from __future__ import annotations

import io
import os
from collections.abc import Callable
from dataclasses import dataclass
from statistics import median
from typing import Any

from PIL import Image

from mainflow.contracts import CONTRACT_VERSION, GenreProfile, ImageStyle
from mainflow.image_backends import remove_flat_background
from mainflow.image_generation import ImageAssetPlan, is_animated_character

SPRITE_SHEETS_ENVIRONMENT_KEY = "MAINFLOW_IMAGE_SPRITE_SHEETS"
SHEET_MODE_ENVIRONMENT_KEY = "MAINFLOW_IMAGE_SPRITE_SHEET_MODE"
SHEET_MODES = ("auto", "ai", "transform")
SHEET_MEDIA_TYPE = "image/png"
# Frames keep the character's feet on this row so clips do not jitter.
PIVOT = (0.5, 0.0)
# validate_sheet() accepts per-frame character heights within this range of
# the first frame of the first animation (a jump crouch is noticeably shorter).
FRAME_HEIGHT_TOLERANCE = (0.6, 1.4)
# ai strips: a frame's average color may differ from the base sprite's by at
# most this RGB distance before the strip is rejected as a different character.
MAX_FRAME_COLOR_DISTANCE = 70.0
ALPHA_THRESHOLD = 128
# ai strips: frames whose height is within this share of the median frame are
# scaled to the same height (drawing jitter); larger differences are kept.
SIZE_JITTER_TOLERANCE = 0.12

StripSource = Callable[["AnimationSpec"], bytes]


@dataclass(frozen=True)
class Keyframe:
    """One transform frame, in units of ``frame_height // 32`` pixels.

    ``bob`` moves the character up (< 0) or down, ``squash`` removes (> 0) or
    duplicates (< 0) torso rows, ``stride`` spreads the legs apart, ``tuck``
    shortens the legs, ``lean`` shifts the head forward (> 0) relative to the
    feet, ``shift`` moves the whole character sideways and ``flash`` brightens
    it.  ``bob`` is also applied to ai frames so jumps and runs keep their
    vertical motion after the frames are foot-aligned.
    """

    bob: int = 0
    squash: int = 0
    stride: int = 0
    tuck: int = 0
    lean: int = 0
    shift: int = 0
    flash: float = 0.0


@dataclass(frozen=True)
class AnimationSpec:
    name: str
    fps: int
    loop: bool
    keyframes: tuple[Keyframe, ...]
    # How the ai strip prompt describes the motion.
    ai_description: str


IDLE = AnimationSpec(
    "idle",
    fps=6,
    loop=True,
    keyframes=(Keyframe(), Keyframe(squash=1), Keyframe(squash=1), Keyframe()),
    ai_description="a calm idle loop with subtle breathing, feet planted",
)
RUN = AnimationSpec(
    "run",
    fps=12,
    loop=True,
    keyframes=(
        Keyframe(stride=2, squash=1, lean=1),  # contact
        Keyframe(stride=1, bob=-1, lean=1),
        Keyframe(bob=-2, squash=-1, lean=1),  # passing, highest point
        Keyframe(stride=2, squash=1, lean=1),
        Keyframe(stride=1, bob=-1, lean=1),
        Keyframe(bob=-2, squash=-1, lean=1),
    ),
    ai_description=(
        "a running cycle with legs alternating forward and back and arms swinging, "
        "body leaning slightly forward"
    ),
)
JUMP = AnimationSpec(
    "jump",
    fps=10,
    loop=False,
    keyframes=(
        Keyframe(squash=2, stride=1),  # crouch before take-off
        Keyframe(bob=-5, tuck=2, squash=-1),  # airborne, legs tucked
        Keyframe(squash=2, stride=2),  # landing
    ),
    ai_description=(
        "a jump: crouching before take-off, airborne with knees tucked up, landing with bent knees"
    ),
)
WALK = AnimationSpec(
    "walk",
    fps=10,
    loop=True,
    keyframes=(
        Keyframe(stride=1),
        Keyframe(bob=-1),
        Keyframe(),
        Keyframe(stride=1),
        Keyframe(bob=-1),
        Keyframe(),
    ),
    ai_description="a walking cycle with legs alternating and arms swinging gently",
)
HIT = AnimationSpec(
    "hit",
    fps=12,
    loop=False,
    keyframes=(
        Keyframe(shift=-2, lean=-2, flash=0.8),
        Keyframe(shift=-1, lean=-1, flash=0.3),
        Keyframe(),
    ),
    ai_description="getting hit: recoiling backwards, then recovering to a standing pose",
)

# Default animation sets per genre until the asset request carries an
# explicit animation list.
# TODO: read the list from the asset request once the contract adds it.
GENRE_ANIMATIONS: dict[GenreProfile, tuple[AnimationSpec, ...]] = {
    "Platformer": (IDLE, RUN, JUMP),
    "SurvivorLike": (IDLE, WALK, HIT),
    "TowerDefense": (WALK, HIT),
}


def sprite_sheets_enabled() -> bool:
    value = os.environ.get(SPRITE_SHEETS_ENVIRONMENT_KEY, "on").strip().lower()
    return value not in ("off", "false", "0", "no")


def sheet_mode() -> str:
    mode = (os.environ.get(SHEET_MODE_ENVIRONMENT_KEY) or "auto").strip().lower()
    if mode not in SHEET_MODES:
        raise ValueError(
            f"{SHEET_MODE_ENVIRONMENT_KEY} must be one of {', '.join(SHEET_MODES)}, got {mode!r}"
        )
    return mode


def animations_for(plan: ImageAssetPlan, genre: GenreProfile) -> tuple[AnimationSpec, ...]:
    """Return the animations to build for a planned asset, or ``()``."""

    if not is_animated_character(plan, genre):
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
    strip_source: StripSource | None = None,
) -> tuple[bytes, dict[str, Any]]:
    """Return the sheet PNG and its metadata for ``animations``.

    With ``strip_source`` each animation is first tried as an ai strip; any
    failure falls back to transform frames for that animation only.  The
    reason is kept in ``metadata["fallbacks"]``.
    """

    if not animations:
        raise ValueError("At least one animation is required for a sprite sheet")
    with Image.open(io.BytesIO(base_png)) as source:
        base = source.convert("RGBA")
    frame_width, frame_height = base.size
    bounding_box = base.getchannel("A").getbbox()
    if bounding_box is None:
        raise ValueError("Base sprite has no visible pixels to animate")
    character = base.crop(bounding_box)
    unit = max(1, frame_height // 32)
    pixel_art = style == "Pixel Art"

    sources: dict[str, str] = {}
    fallbacks: dict[str, str] = {}
    rows: list[list[Image.Image]] = []
    for animation in animations:
        frames: list[Image.Image] | None = None
        if strip_source is not None:
            try:
                frames = _ai_frames(
                    strip_source(animation),
                    animation,
                    character,
                    frame_width,
                    frame_height,
                    unit,
                    pixel_art,
                )
                sources[animation.name] = "ai"
            except Exception as error:  # 어떤 실패든 이 애니메이션만 transform으로 대체
                fallbacks[animation.name] = f"{type(error).__name__}: {error}"
        if frames is None:
            frames = [
                _render_frame(character, keyframe, frame_width, frame_height, unit)
                for keyframe in animation.keyframes
            ]
            sources[animation.name] = "transform"
        rows.append(frames)

    columns = max(len(frames) for frames in rows)
    sheet = Image.new("RGBA", (frame_width * columns, frame_height * len(rows)))
    for row, frames in enumerate(rows):
        for column, frame in enumerate(frames):
            sheet.alpha_composite(frame, (column * frame_width, row * frame_height))
    if pixel_art:
        # Every frame uses the base sprite's colors, so nothing flickers.
        sheet = palette_lock(sheet, character)

    output = io.BytesIO()
    sheet.save(output, format="PNG", optimize=True)
    metadata: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "asset_id": plan.asset_id,
        "unity_binding_key": plan.unity_binding_key,
        "frame_width": frame_width,
        "frame_height": frame_height,
        "columns": columns,
        "rows": len(rows),
        "pivot": list(PIVOT),
        "animations": {
            animation.name: {
                "row": row,
                "frames": len(rows[row]),
                "fps": animation.fps,
                "loop": animation.loop,
                "source": sources[animation.name],
            }
            for row, animation in enumerate(animations)
        },
    }
    if fallbacks:
        metadata["fallbacks"] = fallbacks
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


def palette_lock(image: Image.Image, reference: Image.Image) -> Image.Image:
    """Map ``image`` onto the opaque colors of ``reference`` with hard alpha."""

    colors = [pixel[:3] for pixel in reference.get_flattened_data() if pixel[3] >= ALPHA_THRESHOLD]
    if not colors:
        return image
    strip = Image.new("RGB", (len(colors), 1))
    strip.putdata(colors)
    palette = strip.quantize(
        colors=min(256, len(set(colors))),
        method=Image.Quantize.MEDIANCUT,
        dither=Image.Dither.NONE,
    )
    alpha = image.getchannel("A").point(lambda value: 255 if value >= ALPHA_THRESHOLD else 0)
    locked = image.convert("RGB").quantize(palette=palette, dither=Image.Dither.NONE)
    result = locked.convert("RGBA")
    result.putalpha(alpha)
    return result


# ---------------------------------------------------------------------------
# transform frames (integer pixel operations only)
# ---------------------------------------------------------------------------
def _render_frame(
    character: Image.Image,
    keyframe: Keyframe,
    frame_width: int,
    frame_height: int,
    unit: int,
) -> Image.Image:
    body = character
    if keyframe.squash:
        body = _resize_rows(body, keyframe.squash * unit, band=(0.35, 0.72))
    if keyframe.tuck:
        body = _resize_rows(body, keyframe.tuck * unit, band=(0.72, 0.95))
    if keyframe.stride:
        body = _spread_legs(body, keyframe.stride * unit)
    if keyframe.lean:
        body = _lean(body, keyframe.lean * unit)
    if keyframe.flash:
        white = Image.new("RGBA", body.size, (255, 255, 255, 255))
        white.putalpha(body.getchannel("A"))
        body = Image.blend(body, white, keyframe.flash)

    frame = Image.new("RGBA", (frame_width, frame_height), (0, 0, 0, 0))
    left = frame_width // 2 - _torso_center(body) + keyframe.shift * unit
    top = max(0, frame_height - body.height + keyframe.bob * unit)
    # The canvas is empty, so a plain paste copies pixels and alpha exactly and
    # clips anything pushed past the frame edge.
    frame.paste(body, (left, top))
    return frame


def _resize_rows(image: Image.Image, rows: int, band: tuple[float, float]) -> Image.Image:
    """Remove (``rows`` > 0) or duplicate (< 0) evenly spaced rows inside ``band``."""

    start = int(image.height * band[0])
    end = max(start + 1, int(image.height * band[1]))
    count = min(abs(rows), end - start - 1)
    if count <= 0:
        return image
    step = (end - start) / count
    chosen = {start + int(step * index + step / 2) for index in range(count)}
    order: list[int] = []
    for y in range(image.height):
        if y in chosen:
            if rows < 0:
                order.extend((y, y))
            continue
        order.append(y)
    result = Image.new("RGBA", (image.width, len(order)))
    for target_y, source_y in enumerate(order):
        result.paste(image.crop((0, source_y, image.width, source_y + 1)), (0, target_y))
    return result


def _spread_legs(image: Image.Image, pixels: int) -> Image.Image:
    """Move the left and right halves of the leg region apart by ``pixels`` each."""

    top = int(image.height * 0.7)
    split = _feet_center(image)
    result = Image.new("RGBA", (image.width + 2 * pixels, image.height))
    result.paste(image.crop((0, 0, image.width, top)), (pixels, 0))
    result.paste(image.crop((0, top, split, image.height)), (0, top))
    right = image.crop((split, top, image.width, image.height))
    result.alpha_composite(right, (split + 2 * pixels, top))
    return result


def _lean(image: Image.Image, pixels: int) -> Image.Image:
    """Shear by shifting rows: the top moves ``pixels`` sideways, the feet stay."""

    result = Image.new("RGBA", (image.width + abs(pixels), image.height))
    base_x = abs(pixels) if pixels < 0 else 0
    for y in range(image.height):
        offset = round(pixels * (1 - y / max(1, image.height - 1)))
        result.paste(image.crop((0, y, image.width, y + 1)), (base_x + offset, y))
    return result


def _feet_center(image: Image.Image) -> int:
    """Horizontal center of mass of the bottom quarter (the feet)."""

    return _center_of_mass(image, 0.75, 1.0)


def _torso_center(image: Image.Image) -> int:
    """Horizontal center of mass of the torso band.

    Frames are aligned on the torso, not the feet, so alternating legs in a
    run cycle do not slide the whole body sideways.
    """

    return _center_of_mass(image, 0.3, 0.75)


def _center_of_mass(image: Image.Image, top_share: float, bottom_share: float) -> int:
    top = int(image.height * top_share)
    bottom = max(top + 1, int(image.height * bottom_share))
    band = image.getchannel("A").crop((0, top, image.width, bottom))
    columns = band.resize((band.width, 1), Image.Resampling.BOX)
    weights = list(columns.get_flattened_data())
    total = sum(weights)
    if total == 0:
        return image.width // 2
    return round(sum(x * weight for x, weight in enumerate(weights)) / total)


# ---------------------------------------------------------------------------
# ai frames
# ---------------------------------------------------------------------------
def _ai_frames(
    strip_png: bytes,
    animation: AnimationSpec,
    character: Image.Image,
    frame_width: int,
    frame_height: int,
    unit: int,
    pixel_art: bool,
) -> list[Image.Image]:
    with Image.open(io.BytesIO(strip_png)) as source:
        strip = source.convert("RGBA")
    if strip.getchannel("A").getextrema()[0] == 255:
        strip = remove_flat_background(strip)
    parts = split_strip(strip, len(animation.keyframes))

    # Small size differences between frames are drawing jitter and are
    # normalized away; larger ones are intended poses (a crouch, a tuck) and
    # keep their size relative to the median frame.
    typical = median(part.height for part in parts)
    scales = [
        character.height / part.height
        if abs(part.height / typical - 1) <= SIZE_JITTER_TOLERANCE
        else character.height / typical
        for part in parts
    ]
    lifts = [-keyframe.bob * unit for keyframe in animation.keyframes]
    # Shrink everything together if any frame would not fit around its torso.
    half_width = max(
        max(_torso_center(part), part.width - _torso_center(part)) * scale
        for part, scale in zip(parts, scales, strict=True)
    )
    tallest = max(
        part.height * scale + lift for part, scale, lift in zip(parts, scales, lifts, strict=True)
    )
    fit = min(1.0, (frame_width / 2) / half_width, frame_height / tallest)
    scales = [scale * fit for scale in scales]

    resample = Image.Resampling.BOX if pixel_art else Image.Resampling.LANCZOS
    reference_color = _mean_color(character)
    frames: list[Image.Image] = []
    for index, (part, scale, lift) in enumerate(zip(parts, scales, lifts, strict=True)):
        body = part.resize(
            (max(1, round(part.width * scale)), max(1, round(part.height * scale))),
            resample,
        )
        if pixel_art:
            body = palette_lock(body, character)
        distance = _color_distance(_mean_color(body), reference_color)
        if distance > MAX_FRAME_COLOR_DISTANCE:
            raise ValueError(
                f"frame {index + 1} colors differ from the base sprite (distance {distance:.0f})"
            )
        frame = Image.new("RGBA", (frame_width, frame_height), (0, 0, 0, 0))
        left = frame_width // 2 - _torso_center(body)
        top = max(0, frame_height - body.height - lift)
        frame.paste(body, (left, top))
        frames.append(frame)
    return frames


def split_strip(strip: Image.Image, count: int) -> list[Image.Image]:
    """Split a horizontal strip into ``count`` frames cropped to their pixels.

    Frames are separated by empty columns.  If that does not give ``count``
    frames, an even split is accepted only when no character crosses a cell
    boundary.  Otherwise ``ValueError`` is raised.
    """

    alpha = strip.getchannel("A").point(lambda value: 255 if value >= 32 else 0)
    column_means = list(alpha.resize((alpha.width, 1), Image.Resampling.BOX).get_flattened_data())
    peak = max(column_means)
    if peak == 0:
        raise ValueError("strip is empty")
    occupied = [mean > peak * 0.03 for mean in column_means]

    runs = _runs(occupied)
    # Join pieces of one character separated by a thin gap (e.g. a staff).
    merge_gap = max(2, round(strip.width * 0.015))
    merged: list[list[int]] = []
    for start, end in runs:
        if merged and start - merged[-1][1] <= merge_gap:
            merged[-1][1] = end
        else:
            merged.append([start, end])
    min_width = max(2, round(strip.width * 0.02))
    frames_x = [(start, end) for start, end in merged if end - start >= min_width]

    if len(frames_x) != count:
        frames_x = _split_at_valleys(column_means, peak, count)
        if frames_x is None:
            raise ValueError(f"expected {count} frames in the strip, found {len(merged)}")

    parts: list[Image.Image] = []
    for start, end in frames_x:
        part = strip.crop((start, 0, end, strip.height))
        bounding_box = part.getchannel("A").point(lambda value: 255 if value >= 32 else 0).getbbox()
        if bounding_box is None:
            raise ValueError("a frame in the strip is empty")
        parts.append(part.crop(bounding_box))
    return parts


def _split_at_valleys(
    column_means: list[float],
    peak: float,
    count: int,
) -> list[tuple[int, int]] | None:
    """Cut touching frames at the thinnest column near each expected boundary.

    Frames that only touch (a staff tip reaching the next frame) leave a thin
    valley in the column coverage.  Returns ``None`` when a boundary has no
    such valley, i.e. the characters really overlap.
    """

    width = len(column_means)
    occupied = [index for index, mean in enumerate(column_means) if mean > peak * 0.03]
    left, right = occupied[0], occupied[-1] + 1
    cell = (right - left) / count
    cuts = [left]
    for index in range(1, count):
        expected = left + cell * index
        lo = max(cuts[-1] + 1, round(expected - cell / 3))
        hi = min(width - 1, round(expected + cell / 3))
        if lo >= hi:
            return None
        cut = min(range(lo, hi), key=lambda x: column_means[x])
        if column_means[cut] > peak * 0.25:
            return None
        cuts.append(cut)
    cuts.append(right)
    return [(start, end) for start, end in zip(cuts, cuts[1:], strict=False)]


def _runs(flags: list[bool]) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index, flag in enumerate([*flags, False]):
        if flag and start is None:
            start = index
        elif not flag and start is not None:
            runs.append((start, index))
            start = None
    return runs


def _mean_color(image: Image.Image) -> tuple[float, float, float]:
    pixels = [pixel for pixel in image.get_flattened_data() if pixel[3] >= ALPHA_THRESHOLD]
    if not pixels:
        return (0.0, 0.0, 0.0)
    return tuple(sum(pixel[channel] for pixel in pixels) / len(pixels) for channel in range(3))  # type: ignore[return-value]


def _color_distance(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b, strict=True)) ** 0.5

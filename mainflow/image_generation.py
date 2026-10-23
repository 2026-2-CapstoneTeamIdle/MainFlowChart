"""Image generation and validation logic for the ``generate_image`` and
``validate_image`` nodes.

The asset list comes from the game design's ``image_asset_request``
(``AssetGenerationRequest``).  Each requested asset keeps its ``asset_id`` and
``unity_binding_key`` unchanged.  The generator sits behind the
``ImageGenerator`` protocol so an AI backend (see ``image_backends``) can
replace the deterministic ``PlaceholderImageGenerator`` without changing the
nodes.  PNG encoding and decoding use only the standard library.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from typing import Protocol, cast

from game_pipeline.asset_specs import IMAGE_SIZES, classify_image_kind
from mainflow.contracts import (
    AssetGenerationItem,
    AssetGenerationRequest,
    GenreProfile,
    ImageAssetKind,
    ImageGenerationSpec,
    ImageStyle,
    MoodStyle,
    ValidationCriterion,
    Viewpoint,
)

ImageKind = ImageAssetKind
RGBA = tuple[int, int, int, int]

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PNG_MEDIA_TYPE = "image/png"
# Kinds drawn over a game scene must keep a transparent background.
TRANSPARENT_KINDS: frozenset[ImageKind] = frozenset({"sprite", "portrait", "ui"})

# Backwards-compatible exports for image backends and focused tests.
KIND_SIZES = IMAGE_SIZES

KIND_PROMPTS: dict[ImageKind, str] = {
    "sprite": "A 2D game sprite",
    "portrait": "A 2D character portrait for dialogue scenes",
    "ui": "A 2D game UI element",
    "tileset": "A seamless 2D tileset texture arranged as a grid of tiles",
    "illustration": "A 2D card illustration",
    "background": "A 2D game background scene",
}

STYLE_PALETTES: dict[ImageStyle, tuple[RGBA, RGBA, RGBA]] = {
    # (primary, secondary, background)
    "Pixel Art": ((214, 69, 65, 255), (52, 101, 164, 255), (35, 39, 58, 255)),
    "Anime": ((255, 143, 171, 255), (120, 180, 255, 255), (250, 235, 245, 255)),
    "Cartoon": ((255, 196, 0, 255), (0, 166, 237, 255), (204, 238, 255, 255)),
    "Realistic": ((122, 98, 74, 255), (78, 102, 66, 255), (160, 170, 165, 255)),
    "Low Poly": ((90, 200, 160, 255), (240, 120, 80, 255), (60, 70, 110, 255)),
    "Custom": ((150, 150, 160, 255), (90, 90, 110, 255), (220, 220, 225, 255)),
}

STYLE_PROMPTS: dict[ImageStyle, str] = {
    "Pixel Art": "pixel art, limited palette, crisp pixels",
    "Anime": "anime style, clean line art, cel shading",
    "Cartoon": "cartoon style, bold outlines, flat colors",
    "Realistic": "realistic, detailed textures, natural lighting",
    "Low Poly": "low poly 3D render, flat shaded facets",
    "Custom": "match the art style, palette and rendering of the reference image",
}

MOOD_PROMPTS: dict[MoodStyle, str] = {
    "Cyberpunk": "cyberpunk, neon lights, high-tech city",
    "Medieval": "medieval, castles and old stone",
    "Modern": "modern everyday setting",
    "Fantasy": "high fantasy, magical",
    "Horror": "dark horror atmosphere, eerie",
    "Cozy": "cozy, warm and soft",
}

VIEWPOINT_PROMPTS: dict[Viewpoint, str] = {
    "사이드뷰": "side view",
    "탑다운": "top-down view",
    "쿼터뷰": "isometric three-quarter view",
    "고정 화면": "fixed single-screen front view",
}

# validate_image looks for this clause in an asset's recorded prompt to know
# that the asset must have transparent pixels.
TRANSPARENT_PROMPT = "isolated on a transparent background, single centered subject"
OPAQUE_PROMPT = "fills the whole canvas, no transparency"

# Generic game subjects ("jumping hero", "gold coin") tend to drift toward
# famous franchise characters, which the provider's output moderation blocks.
ORIGINAL_DESIGN_PROMPT = "original design, not based on any existing game, franchise or character"


@dataclass(frozen=True)
class ImageAssetPlan:
    """One requested image, derived from an ``AssetGenerationItem``."""

    asset_id: str
    purpose: str
    description: str
    required: bool
    filename: str
    unity_binding_key: str
    kind: ImageKind
    generation_spec: ImageGenerationSpec

    @property
    def transparent(self) -> bool:
        return self.kind in TRANSPARENT_KINDS

    @property
    def size(self) -> tuple[int, int]:
        return self.generation_spec["width"], self.generation_spec["height"]


def classify_kind(purpose: str, description: str) -> ImageKind:
    return classify_image_kind(purpose, description)


def plan_from_item(item: AssetGenerationItem) -> ImageAssetPlan:
    filename = item["suggested_filename"]
    if not filename.lower().endswith(".png"):
        filename = f"{item['asset_id']}.png"
    spec = cast(ImageGenerationSpec, item["generation_spec"])
    return ImageAssetPlan(
        asset_id=item["asset_id"],
        purpose=item["purpose"],
        description=item["description"],
        required=item["required"],
        filename=filename,
        unity_binding_key=item["unity_binding_key"],
        kind=spec["kind"],
        generation_spec=spec,
    )


def plan_assets(request: AssetGenerationRequest) -> list[ImageAssetPlan]:
    return [plan_from_item(item) for item in request["assets"] if item["asset_type"] == "image"]


def build_prompt(plan: ImageAssetPlan, request: AssetGenerationRequest) -> str:
    background = TRANSPARENT_PROMPT if plan.transparent else OPAQUE_PROMPT
    return (
        f'{KIND_PROMPTS[plan.kind]} for the {request["genre"]} game "{request["game_title"]}": '
        f"{plan.description} (role: {plan.purpose}). "
        f"Art style: {STYLE_PROMPTS[request['image_style']]}. "
        f"Mood: {MOOD_PROMPTS[request['mood_style']]}. "
        f"Viewpoint: {VIEWPOINT_PROMPTS[request['viewpoint']]}. "
        f"{background}, no text or letters, {ORIGINAL_DESIGN_PROMPT}"
    )


@dataclass(frozen=True)
class ReferenceImage:
    content: bytes
    media_type: str


@dataclass(frozen=True)
class ImageRequest:
    plan: ImageAssetPlan
    style: ImageStyle
    mood_style: MoodStyle
    viewpoint: Viewpoint
    genre: GenreProfile
    width: int
    height: int
    prompt: str
    reference: ReferenceImage | None = None


class ImageGenerator(Protocol):
    """Backend that turns one ``ImageRequest`` into PNG bytes."""

    name: str

    def generate(self, request: ImageRequest) -> bytes: ...


class PlaceholderImageGenerator:
    """Deterministic shape-based generator used until an AI backend is wired."""

    name = "placeholder"

    def generate(self, request: ImageRequest) -> bytes:
        primary, secondary, backdrop = STYLE_PALETTES[request.style]
        variant = zlib.crc32(request.prompt.encode("utf-8"))
        # The workflow embeds its variation seed in the prompt. This keeps an
        # offline run reproducible without drawing the same placeholder forever.
        if variant % 2:
            primary, secondary = secondary, primary
        primary = _vary_color(primary, variant, 0)
        secondary = _vary_color(secondary, variant, 13)
        width, height = request.width, request.height
        # Pixel Art is drawn on a coarse grid so the result looks blocky.
        block = max(1, width // 16) if request.style == "Pixel Art" else 1

        rows: list[list[RGBA]] = []
        for y in range(height):
            row: list[RGBA] = []
            for x in range(width):
                sx, sy = (x // block) * block, (y // block) * block
                row.append(
                    self._pixel(
                        request.plan.kind,
                        sx,
                        sy,
                        width,
                        height,
                        primary,
                        secondary,
                        backdrop,
                        variant,
                    )
                )
            rows.append(row)
        return encode_png(rows)

    @staticmethod
    def _pixel(
        kind: ImageKind,
        x: int,
        y: int,
        width: int,
        height: int,
        primary: RGBA,
        secondary: RGBA,
        backdrop: RGBA,
        variant: int = 0,
    ) -> RGBA:
        transparent: RGBA = (0, 0, 0, 0)
        u = (x + 0.5) / width - 0.5
        v = (y + 0.5) / height - 0.5

        if kind == "background":
            # Vertical gradient from backdrop to secondary, with a ground band.
            if v > 0.3:
                return primary
            t = y / max(1, height - 1)
            return _mix(backdrop, secondary, t * 0.6)
        if kind == "tileset":
            # 4x4 grid of bordered tiles.
            tile_width, tile_height = max(1, width // 4), max(1, height // 4)
            tx, ty = x % tile_width, y % tile_height
            edge = min(tx, ty, tile_width - 1 - tx, tile_height - 1 - ty)
            border = max(1, tile_width // (6 + variant % 4))
            if variant % 3 == 0:
                accent = edge < border
            elif variant % 3 == 1:
                accent = edge < border or (x // tile_width + y // tile_height) % 2 == 0
            else:
                accent = edge < border or (tx + ty + variant) % max(2, tile_width // 3) == 0
            return secondary if accent else primary
        if kind == "illustration":
            # Diamond emblem on a filled card.
            return primary if abs(u) + abs(v) < 0.35 else backdrop
        if kind == "ui":
            # Hollow square frame.
            outer = max(abs(u), abs(v)) < 0.45
            inner = max(abs(u), abs(v)) < 0.35
            return primary if outer and not inner else transparent
        # sprite / portrait: a small family of readable debug silhouettes.
        head_x = (-0.06, 0.0, 0.06)[variant % 3]
        body_width = (0.24, 0.28, 0.32)[(variant // 3) % 3]
        if (u - head_x) ** 2 + (v + 0.22) ** 2 < 0.15**2:
            return secondary
        if (u / body_width) ** 2 + ((v - 0.15) / 0.3) ** 2 < 1.0:
            return primary
        return transparent


def _mix(a: RGBA, b: RGBA, t: float) -> RGBA:
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(4))  # type: ignore[return-value]


def _vary_color(color: RGBA, variant: int, shift: int) -> RGBA:
    """Apply a small deterministic tint without changing transparency."""

    channels = []
    for index, value in enumerate(color[:3]):
        delta = ((variant >> (shift + index * 5)) & 0x1F) - 16
        channels.append(max(0, min(255, value + delta)))
    return channels[0], channels[1], channels[2], color[3]


# ---------------------------------------------------------------------------
# PNG helpers (RGBA, 8-bit, no external dependency)
# ---------------------------------------------------------------------------
def encode_png(rows: list[list[RGBA]]) -> bytes:
    height = len(rows)
    width = len(rows[0]) if rows else 0
    if width == 0 or height == 0:
        raise ValueError("PNG must have at least one pixel")
    raw = bytearray()
    for row in rows:
        if len(row) != width:
            raise ValueError("All PNG rows must have the same width")
        raw.append(0)  # filter type: None
        for pixel in row:
            raw.extend(pixel)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        PNG_SIGNATURE
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


@dataclass(frozen=True)
class PngInfo:
    width: int
    height: int
    has_alpha: bool
    has_transparent_pixel: bool


def inspect_png(content: bytes) -> PngInfo:
    """Parse and fully decode an 8-bit RGB/RGBA non-interlaced PNG."""

    if not content.startswith(PNG_SIGNATURE):
        raise ValueError("Not a PNG file")
    position = len(PNG_SIGNATURE)
    header: bytes | None = None
    idat = bytearray()
    while position < len(content):
        if position + 8 > len(content):
            raise ValueError("Truncated PNG chunk header")
        (length,) = struct.unpack(">I", content[position : position + 4])
        kind = content[position + 4 : position + 8]
        data = content[position + 8 : position + 8 + length]
        crc_bytes = content[position + 8 + length : position + 12 + length]
        if len(data) != length or len(crc_bytes) != 4:
            raise ValueError("Truncated PNG chunk")
        if struct.unpack(">I", crc_bytes)[0] != zlib.crc32(kind + data) & 0xFFFFFFFF:
            raise ValueError(f"PNG chunk CRC mismatch: {kind!r}")
        if kind == b"IHDR":
            header = data
        elif kind == b"IDAT":
            idat.extend(data)
        elif kind == b"IEND":
            break
        position += 12 + length
    if header is None or not idat:
        raise ValueError("PNG is missing IHDR or IDAT")

    width, height, bit_depth, color_type, _, _, interlace = struct.unpack(">IIBBBBB", header)
    if bit_depth != 8 or color_type not in (2, 6) or interlace != 0:
        raise ValueError("Only 8-bit RGB/RGBA non-interlaced PNG is supported")
    channels = 4 if color_type == 6 else 3
    raw = zlib.decompress(bytes(idat))
    stride = width * channels + 1
    if len(raw) != stride * height:
        raise ValueError("PNG pixel data size does not match header")

    has_transparent_pixel = False
    previous = bytearray(width * channels)
    for row_start in range(0, len(raw), stride):
        row = _unfilter_row(
            raw[row_start], raw[row_start + 1 : row_start + stride], previous, channels
        )
        if channels == 4 and any(value < 255 for value in row[3::4]):
            has_transparent_pixel = True
        previous = row
    return PngInfo(width, height, channels == 4, has_transparent_pixel)


def _unfilter_row(
    filter_type: int,
    filtered: bytes,
    previous: bytearray,
    bytes_per_pixel: int,
) -> bytearray:
    row = bytearray(filtered)
    for i in range(len(row)):
        left = row[i - bytes_per_pixel] if i >= bytes_per_pixel else 0
        up = previous[i]
        up_left = previous[i - bytes_per_pixel] if i >= bytes_per_pixel else 0
        if filter_type == 0:
            predictor = 0
        elif filter_type == 1:
            predictor = left
        elif filter_type == 2:
            predictor = up
        elif filter_type == 3:
            predictor = (left + up) // 2
        elif filter_type == 4:
            estimate = left + up - up_left
            distances = (abs(estimate - left), abs(estimate - up), abs(estimate - up_left))
            predictor = (left, up, up_left)[distances.index(min(distances))]
        else:
            raise ValueError(f"Unknown PNG filter type: {filter_type}")
        row[i] = (row[i] + predictor) & 0xFF
    return row


# ---------------------------------------------------------------------------
# Validation criteria shared by the asset validation spec and validate_image
# ---------------------------------------------------------------------------
IMAGE_CRITERIA: tuple[ValidationCriterion, ...] = (
    {
        "criterion_id": "image-plan-complete",
        "target": "image",
        "description": "Every required image asset in the image request was generated",
        "required": True,
    },
    {
        "criterion_id": "image-file-valid",
        "target": "image",
        "description": "Each image is a readable PNG whose checksum matches",
        "required": True,
    },
    {
        "criterion_id": "image-size-match",
        "target": "image",
        "description": "Decoded width/height match the declared asset size",
        "required": True,
    },
    {
        "criterion_id": "image-transparency",
        "target": "image",
        "description": "Sprites, portraits and UI drawn over the scene have transparent pixels",
        "required": True,
    },
)


def image_criteria() -> list[ValidationCriterion]:
    return [dict(item) for item in IMAGE_CRITERIA]  # type: ignore[misc]

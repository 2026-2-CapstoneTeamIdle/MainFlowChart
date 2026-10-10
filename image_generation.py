"""Image generation and validation logic for the ``generate_image`` and
``validate_image`` agents.

The generator sits behind the ``ImageGenerator`` protocol so a real AI backend
(OpenAI, Imagen, Stable Diffusion, ...) can replace the deterministic
``PlaceholderImageGenerator`` without changing the graph nodes.  PNG encoding
and decoding use only the standard library.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from typing import Literal, Protocol

from contracts import (
    GameGenre,
    ImageStyle,
    QualityLevel,
    ValidationCriterion,
)


ImageRole = Literal["character", "enemy", "tile", "item", "ui", "background"]
RGBA = tuple[int, int, int, int]

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PNG_MEDIA_TYPE = "image/png"
# Roles drawn over a game scene must keep a transparent background.
TRANSPARENT_ROLES: frozenset[ImageRole] = frozenset(
    {"character", "enemy", "item", "ui"}
)


@dataclass(frozen=True)
class ImageAssetPlan:
    """One image the game expects.  ``key`` is shared with the game agent."""

    key: str
    name: str
    role: ImageRole
    description: str

    @property
    def asset_id(self) -> str:
        return f"image-{self.key}"

    @property
    def filename(self) -> str:
        return f"{self.key}.png"


# Standard asset list per genre.  ``generate_image`` runs in parallel with
# ``design_game_logic``, so both agents rely on this list instead of each
# other's output.  Change it only together with the game agent owner.
GENRE_ASSET_PLANS: dict[GameGenre, tuple[ImageAssetPlan, ...]] = {
    "Action": (
        ImageAssetPlan("player", "Player", "character", "hero character"),
        ImageAssetPlan("enemy_basic", "Basic Enemy", "enemy", "basic enemy"),
        ImageAssetPlan("projectile", "Projectile", "item", "bullet projectile"),
        ImageAssetPlan("background", "Background", "background", "battle stage"),
    ),
    "RPG": (
        ImageAssetPlan("player", "Player", "character", "adventurer hero"),
        ImageAssetPlan("npc_villager", "Villager", "character", "friendly villager"),
        ImageAssetPlan("enemy_slime", "Slime", "enemy", "slime monster"),
        ImageAssetPlan("item_potion", "Potion", "item", "healing potion"),
        ImageAssetPlan("background", "Background", "background", "fantasy village"),
    ),
    "Platformer": (
        ImageAssetPlan("player", "Player", "character", "jumping hero"),
        ImageAssetPlan("enemy_basic", "Basic Enemy", "enemy", "walking enemy"),
        ImageAssetPlan("tile_ground", "Ground Tile", "tile", "ground tile"),
        ImageAssetPlan("item_coin", "Coin", "item", "gold coin"),
        ImageAssetPlan("background", "Background", "background", "side-scrolling sky"),
    ),
    "Puzzle": (
        ImageAssetPlan("tile_block_red", "Red Block", "tile", "red puzzle block"),
        ImageAssetPlan("tile_block_blue", "Blue Block", "tile", "blue puzzle block"),
        ImageAssetPlan("cursor", "Cursor", "ui", "selection cursor"),
        ImageAssetPlan("background", "Background", "background", "puzzle board"),
    ),
    "Simulation": (
        ImageAssetPlan("character_worker", "Worker", "character", "town worker"),
        ImageAssetPlan("building_house", "House", "item", "small house building"),
        ImageAssetPlan("tile_grass", "Grass Tile", "tile", "grass tile"),
        ImageAssetPlan("background", "Background", "background", "town map"),
    ),
}

# Sprite edge length in pixels per quality level.
SPRITE_SIZE: dict[QualityLevel, int] = {"Low": 32, "Medium": 64, "High": 128}

STYLE_PALETTES: dict[ImageStyle, tuple[RGBA, RGBA, RGBA]] = {
    # (primary, secondary, background)
    "Pixel Art": ((214, 69, 65, 255), (52, 101, 164, 255), (35, 39, 58, 255)),
    "Anime": ((255, 143, 171, 255), (120, 180, 255, 255), (250, 235, 245, 255)),
    "Cartoon": ((255, 196, 0, 255), (0, 166, 237, 255), (204, 238, 255, 255)),
    "Realistic": ((122, 98, 74, 255), (78, 102, 66, 255), (160, 170, 165, 255)),
    "Low Poly": ((90, 200, 160, 255), (240, 120, 80, 255), (60, 70, 110, 255)),
}

STYLE_PROMPTS: dict[ImageStyle, str] = {
    "Pixel Art": "pixel art, limited palette, crisp pixels",
    "Anime": "anime style, clean line art, cel shading",
    "Cartoon": "cartoon style, bold outlines, flat colors",
    "Realistic": "realistic, detailed textures, natural lighting",
    "Low Poly": "low poly 3D render, flat shaded facets",
}


# Generic game subjects ("jumping hero", "gold coin") tend to drift toward
# famous franchise characters, which the provider's output moderation blocks.
ORIGINAL_DESIGN_PROMPT = (
    "original design, not based on any existing game, franchise or character"
)


def plan_assets(genre: GameGenre) -> tuple[ImageAssetPlan, ...]:
    return GENRE_ASSET_PLANS[genre]


def asset_size(plan: ImageAssetPlan, quality: QualityLevel) -> tuple[int, int]:
    sprite = SPRITE_SIZE[quality]
    if plan.role == "background":
        return sprite * 4, sprite * 3
    return sprite, sprite


def build_prompt(plan: ImageAssetPlan, style: ImageStyle, genre: GameGenre) -> str:
    background = (
        "transparent background, single centered object"
        if plan.role in TRANSPARENT_ROLES
        else "full scene"
    )
    return (
        f"{plan.description} for a {genre} game, "
        f"{STYLE_PROMPTS[style]}, {background}, "
        f"{ORIGINAL_DESIGN_PROMPT}"
    )


@dataclass(frozen=True)
class ImageRequest:
    plan: ImageAssetPlan
    style: ImageStyle
    genre: GameGenre
    width: int
    height: int
    prompt: str
    quality: QualityLevel = "Medium"


class ImageGenerator(Protocol):
    """Backend that turns one ``ImageRequest`` into PNG bytes."""

    name: str

    def generate(self, request: ImageRequest) -> bytes: ...


class PlaceholderImageGenerator:
    """Deterministic shape-based generator used until an AI backend is wired."""

    name = "placeholder"

    def generate(self, request: ImageRequest) -> bytes:
        primary, secondary, backdrop = STYLE_PALETTES[request.style]
        if request.plan.role in ("enemy", "ui"):
            primary, secondary = secondary, primary
        width, height = request.width, request.height
        # Pixel Art is drawn on a coarse grid so the result looks blocky.
        block = max(1, width // 16) if request.style == "Pixel Art" else 1

        rows: list[list[RGBA]] = []
        for y in range(height):
            row: list[RGBA] = []
            for x in range(width):
                sx, sy = (x // block) * block, (y // block) * block
                row.append(
                    self._pixel(request.plan.role, sx, sy, width, height,
                                primary, secondary, backdrop)
                )
            rows.append(row)
        return encode_png(rows)

    @staticmethod
    def _pixel(
        role: ImageRole,
        x: int,
        y: int,
        width: int,
        height: int,
        primary: RGBA,
        secondary: RGBA,
        backdrop: RGBA,
    ) -> RGBA:
        transparent: RGBA = (0, 0, 0, 0)
        u = (x + 0.5) / width - 0.5
        v = (y + 0.5) / height - 0.5

        if role == "background":
            # Vertical gradient from backdrop to secondary, with a ground band.
            if v > 0.3:
                return primary
            t = y / max(1, height - 1)
            return _mix(backdrop, secondary, t * 0.6)
        if role == "tile":
            edge = min(x, y, width - 1 - x, height - 1 - y)
            return secondary if edge < max(1, width // 16) else primary
        if role == "item":
            # Diamond.
            return primary if abs(u) + abs(v) < 0.35 else transparent
        if role == "ui":
            # Hollow square frame.
            outer = max(abs(u), abs(v)) < 0.45
            inner = max(abs(u), abs(v)) < 0.35
            return primary if outer and not inner else transparent
        # character / enemy: head circle over body ellipse.
        if u * u + (v + 0.22) ** 2 < 0.15**2:
            return secondary
        if (u / 0.3) ** 2 + ((v - 0.15) / 0.3) ** 2 < 1.0:
            return primary
        return transparent


def _mix(a: RGBA, b: RGBA, t: float) -> RGBA:
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(4))  # type: ignore[return-value]


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
        (length,) = struct.unpack(">I", content[position:position + 4])
        kind = content[position + 4:position + 8]
        data = content[position + 8:position + 8 + length]
        crc_bytes = content[position + 8 + length:position + 12 + length]
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

    width, height, bit_depth, color_type, _, _, interlace = struct.unpack(
        ">IIBBBBB", header
    )
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
            raw[row_start], raw[row_start + 1:row_start + stride], previous, channels
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
        "description": "Every planned image asset for the genre was generated",
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
        "description": "Sprites drawn over the scene have transparent pixels",
        "required": True,
    },
)


def image_criteria() -> list[ValidationCriterion]:
    return [dict(item) for item in IMAGE_CRITERIA]  # type: ignore[misc]

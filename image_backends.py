"""AI image generator backends and the post-processing that turns their output
into game-ready PNG assets.

Select a backend with ``MAINFLOW_IMAGE_BACKEND``:

- ``placeholder`` (default): deterministic shapes, no API key needed.
- ``openai``: OpenAI Images API.  Requires ``OPENAI_API_KEY``; the model can be
  overridden with ``MAINFLOW_OPENAI_IMAGE_MODEL``.

API keys are read from the environment only and are never written to the
workspace, the manifest or the logs.
"""

from __future__ import annotations

import base64
import io
import os
from typing import Any

from PIL import Image, ImageDraw

from contracts import QualityLevel
from image_generation import (
    TRANSPARENT_ROLES,
    ImageGenerator,
    ImageRequest,
    PlaceholderImageGenerator,
)


BACKEND_ENVIRONMENT_KEY = "MAINFLOW_IMAGE_BACKEND"
OPENAI_MODEL_ENVIRONMENT_KEY = "MAINFLOW_OPENAI_IMAGE_MODEL"
# gpt-image-1 has stable transparent-background support; newer models can be
# selected through MAINFLOW_OPENAI_IMAGE_MODEL once verified.
DEFAULT_OPENAI_MODEL = "gpt-image-1"

OPENAI_QUALITY: dict[QualityLevel, str] = {
    "Low": "low",
    "Medium": "medium",
    "High": "high",
}
PIXEL_ART_COLORS = 32
# Sprites keep this fraction of the canvas as empty margin after cropping.
SPRITE_MARGIN = 0.08
BACKGROUND_REMOVAL_THRESHOLD = 40


class OpenAIImageGenerator:
    """Generate images with the OpenAI Images API."""

    name = "openai"

    def __init__(
        self,
        model: str | None = None,
        *,
        client: Any | None = None,
        max_retries: int = 3,
        timeout_seconds: float = 120.0,
    ) -> None:
        self.model = model or os.environ.get(
            OPENAI_MODEL_ENVIRONMENT_KEY, DEFAULT_OPENAI_MODEL
        )
        if client is None:
            from openai import OpenAI

            # The SDK retries 429/5xx responses with exponential backoff.
            client = OpenAI(max_retries=max_retries, timeout=timeout_seconds)
        self.client = client

    def generate(self, request: ImageRequest) -> bytes:
        transparent = request.plan.role in TRANSPARENT_ROLES
        response = self.client.images.generate(
            model=self.model,
            prompt=request.prompt,
            size="1536x1024" if request.plan.role == "background" else "1024x1024",
            quality=OPENAI_QUALITY[request.quality],
            background="transparent" if transparent else "opaque",
            output_format="png",
            n=1,
        )
        if not response.data or not response.data[0].b64_json:
            raise RuntimeError("OpenAI image response did not contain image data")
        return postprocess(base64.b64decode(response.data[0].b64_json), request)


def create_image_generator(backend: str | None = None) -> ImageGenerator:
    backend = (backend or os.environ.get(BACKEND_ENVIRONMENT_KEY) or "placeholder")
    backend = backend.strip().lower()
    if backend == "placeholder":
        return PlaceholderImageGenerator()
    if backend == "openai":
        return OpenAIImageGenerator()
    raise ValueError(
        f"Unsupported {BACKEND_ENVIRONMENT_KEY}: {backend!r} "
        "(expected 'placeholder' or 'openai')"
    )


# ---------------------------------------------------------------------------
# Post-processing
# ---------------------------------------------------------------------------
def postprocess(content: bytes, request: ImageRequest) -> bytes:
    """Resize, clean up and re-encode generator output to the planned asset."""

    with Image.open(io.BytesIO(content)) as source:
        image = source.convert("RGBA")

    if request.plan.role in TRANSPARENT_ROLES:
        if not _has_transparency(image):
            image = remove_flat_background(image)
        image = _fit_sprite(image, request.width, request.height, request.style)
    else:
        image = _cover(image, request.width, request.height, request.style)
        image.putalpha(255)

    if request.style == "Pixel Art":
        image = pixelate_palette(image, PIXEL_ART_COLORS)

    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def remove_flat_background(
    image: Image.Image,
    threshold: int = BACKGROUND_REMOVAL_THRESHOLD,
) -> Image.Image:
    """Make a flat background transparent by flood-filling from the corners.

    Fallback for when the API ignores ``background="transparent"``.  It only
    removes regions connected to the corners, so interior colors survive.
    """

    result = image.copy()
    width, height = result.size
    for corner in ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)):
        if result.getpixel(corner)[3] == 0:
            continue
        ImageDraw.floodfill(result, corner, (0, 0, 0, 0), thresh=threshold)
    return result


def pixelate_palette(image: Image.Image, colors: int) -> Image.Image:
    """Reduce colors and snap alpha to fully opaque/transparent pixels."""

    alpha = image.getchannel("A").point(lambda value: 255 if value >= 128 else 0)
    quantized = image.convert("RGB").quantize(
        colors=colors,
        method=Image.Quantize.MEDIANCUT,
        dither=Image.Dither.NONE,
    )
    result = quantized.convert("RGBA")
    result.putalpha(alpha)
    return result


def _has_transparency(image: Image.Image) -> bool:
    minimum_alpha, _ = image.getchannel("A").getextrema()
    return minimum_alpha < 255


def _resample(style: str) -> Image.Resampling:
    # BOX averages whole source blocks, which keeps pixel-art edges crisp.
    return Image.Resampling.BOX if style == "Pixel Art" else Image.Resampling.LANCZOS


def _fit_sprite(image: Image.Image, width: int, height: int, style: str) -> Image.Image:
    """Crop to the visible object and center it with a margin on the canvas."""

    bounding_box = image.getchannel("A").getbbox()
    if bounding_box is not None:
        image = image.crop(bounding_box)
    inner_width = max(1, round(width * (1 - 2 * SPRITE_MARGIN)))
    inner_height = max(1, round(height * (1 - 2 * SPRITE_MARGIN)))
    scale = min(inner_width / image.width, inner_height / image.height)
    resized = image.resize(
        (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
        _resample(style),
    )
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    canvas.alpha_composite(
        resized,
        ((width - resized.width) // 2, (height - resized.height) // 2),
    )
    return canvas


def _cover(image: Image.Image, width: int, height: int, style: str) -> Image.Image:
    """Center-crop to the target aspect ratio, then resize to fill it."""

    target_ratio = width / height
    if image.width / image.height > target_ratio:
        crop_width = round(image.height * target_ratio)
        left = (image.width - crop_width) // 2
        image = image.crop((left, 0, left + crop_width, image.height))
    else:
        crop_height = round(image.width / target_ratio)
        top = (image.height - crop_height) // 2
        image = image.crop((0, top, image.width, top + crop_height))
    return image.resize((width, height), _resample(style))

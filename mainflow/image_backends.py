"""AI image generator backends and the post-processing that turns their output
into game-ready PNG assets.

Select a backend with ``MAINFLOW_IMAGE_BACKEND``:

- ``placeholder`` (default): deterministic shapes, no API key needed.
- ``openai``: OpenAI Images API.  Requires ``OPENAI_API_KEY``; the model and
  rendering quality can be overridden with ``MAINFLOW_OPENAI_IMAGE_MODEL`` and
  ``MAINFLOW_OPENAI_IMAGE_QUALITY``.  A reference image (``Custom`` style) is
  sent through the image edit endpoint.
- ``local``: a local OpenAI-compatible image server such as the team's LocalAI
  (``/v1/images/generations``).  Requires ``MAINFLOW_LOCAL_IMAGE_MODEL`` to name
  an image model installed on that server; text models such as Gemma cannot
  generate images.  See ``LocalImageGenerator`` for the other settings.

API keys are read from the environment only and are never written to the
workspace, the manifest or the logs.
"""

from __future__ import annotations

import base64
import io
import math
import os
import re
import urllib.request
from typing import Any

from PIL import Image, ImageChops, ImageDraw

from mainflow.image_generation import (
    STYLE_PROMPTS,
    ImageGenerator,
    ImageKind,
    ImageRequest,
    PlaceholderImageGenerator,
)

BACKEND_ENVIRONMENT_KEY = "MAINFLOW_IMAGE_BACKEND"
OPENAI_MODEL_ENVIRONMENT_KEY = "MAINFLOW_OPENAI_IMAGE_MODEL"
# gpt-image-1 was shut down on 2026-10-23.  Override with
# MAINFLOW_OPENAI_IMAGE_MODEL when OpenAI retires or replaces this one.
DEFAULT_OPENAI_MODEL = "gpt-image-2.5-sunburst"

OPENAI_QUALITY_ENVIRONMENT_KEY = "MAINFLOW_OPENAI_IMAGE_QUALITY"
DEFAULT_OPENAI_QUALITY = "medium"
OPENAI_QUALITIES = frozenset({"low", "medium", "high"})
OPENAI_SIZES: dict[ImageKind, str] = {
    "sprite": "1024x1024",
    "portrait": "1024x1536",
    "ui": "1024x1024",
    "tileset": "1024x1024",
    "illustration": "1024x1024",
    "background": "1536x1024",
}
PIXEL_ART_COLORS = 32
# Sprites keep this fraction of the canvas as empty margin after cropping.
SPRITE_MARGIN = 0.08
BACKGROUND_REMOVAL_THRESHOLD = 40
# Larger images find the connected background on a reduced copy (much faster).
EXACT_FLOODFILL_MAX_PIXELS = 256 * 256
# Prompt additions tried in order when the provider's safety system blocks a
# result.  Output-stage blocks are usually false positives on a look-alike of
# an existing character, so steering away from a generic look often passes.
# Models that cannot output alpha draw sprites on a flat background, which
# postprocess() removes afterwards.
FLAT_BACKGROUND_PROMPT = " Plain solid white background, no shadow, no scenery."
MODERATION_RETRY_SUFFIXES = (
    "",
    " Give it a unique silhouette and an unusual color scheme.",
    " Use a simple, abstract, generic look with no recognizable features.",
)


class OpenAIImageGenerator:
    """Generate images with the OpenAI Images API."""

    name = "openai"

    def __init__(
        self,
        model: str | None = None,
        *,
        client: Any | None = None,
        quality: str | None = None,
        max_retries: int = 3,
        timeout_seconds: float = 120.0,
    ) -> None:
        self.model = model or os.environ.get(OPENAI_MODEL_ENVIRONMENT_KEY) or DEFAULT_OPENAI_MODEL
        self.quality = (
            quality or os.environ.get(OPENAI_QUALITY_ENVIRONMENT_KEY) or DEFAULT_OPENAI_QUALITY
        ).lower()
        if self.quality not in OPENAI_QUALITIES:
            raise ValueError(
                f"Unsupported {OPENAI_QUALITY_ENVIRONMENT_KEY}: {self.quality!r} "
                "(expected low, medium or high)"
            )
        if client is None:
            from openai import OpenAI

            # The SDK retries 429/5xx responses with exponential backoff.
            client = OpenAI(max_retries=max_retries, timeout=timeout_seconds)
        self.client = client
        # Full-resolution output per asset_id, used as the reference image for
        # animation strips (the post-processed sprite is only 64x64).
        self.raw_outputs: dict[str, bytes] = {}
        # Some models (e.g. gpt-image-2 without the transparency preview)
        # reject background="transparent".  After the first rejection every
        # request asks for a flat background instead.
        self.transparent_supported = True

    def generate(self, request: ImageRequest) -> bytes:
        return self._explain_model_errors(
            lambda: _retry_moderation(
                lambda suffix: self._with_transparency_fallback(
                    request.plan.transparent,
                    lambda background, extra: self._generate_once(
                        request, request.prompt + suffix + extra, background
                    ),
                )
            )
        )

    def _with_transparency_fallback(self, transparent: bool, call: Any) -> bytes:
        """Run ``call(background, prompt_extra)``, retrying opaque if alpha is rejected."""

        if not transparent:
            return call("opaque", "")
        if self.transparent_supported:
            try:
                return call("transparent", "")
            except Exception as error:
                if getattr(error, "param", None) != "background":
                    raise
                self.transparent_supported = False
        return call("opaque", FLAT_BACKGROUND_PROMPT)

    def _explain_model_errors(self, call: Any) -> bytes:
        """Point at the setting to change when OpenAI rejects the model name."""

        try:
            return call()
        except Exception as error:
            if getattr(error, "param", None) != "model":
                raise
            raise RuntimeError(
                f"Image model {self.model!r} is not available ({error}). Set "
                f"{OPENAI_MODEL_ENVIRONMENT_KEY} to a supported model such as {DEFAULT_OPENAI_MODEL}."
            ) from error

    def generate_animation_strip(
        self,
        request: ImageRequest,
        base_png: bytes,
        animation: str,
        frames: int,
        description: str,
    ) -> bytes:
        """Draw one animation as a single horizontal strip of ``frames`` poses.

        The base sprite is sent as the reference image so the character keeps
        its look.  Returns the raw strip PNG; image_spritesheet splits it.
        """

        prompt = (
            f"Sprite sheet of the exact same character as the reference image: {frames} frames "
            f"of {description} ({animation} animation). Frames are arranged left to right in a "
            "single row with even spacing and empty space between them. Every frame shows the "
            "full body facing right at the same scale, with the same face, outfit, colors and "
            f"proportions as the reference. Art style: {STYLE_PROMPTS[request.style]}. "
            "No text, no grid lines, no frame borders, no shadows."
        )

        def call(suffix: str) -> bytes:
            return self._with_transparency_fallback(
                True,
                lambda background, extra: edit(
                    prompt
                    + (" Transparent background." if background == "transparent" else extra)
                    + suffix,
                    background,
                ),
            )

        def edit(full_prompt: str, background: str) -> bytes:
            response = self.client.images.edit(
                model=self.model,
                image=("character.png", base_png, "image/png"),
                prompt=full_prompt,
                size="1536x1024",
                quality=self.quality,
                background=background,
                output_format="png",
                input_fidelity="high",
                n=1,
            )
            if not response.data or not response.data[0].b64_json:
                raise RuntimeError("OpenAI image response did not contain image data")
            return base64.b64decode(response.data[0].b64_json)

        return self._explain_model_errors(lambda: _retry_moderation(call))

    def _generate_once(self, request: ImageRequest, prompt: str, background: str) -> bytes:
        options: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "size": OPENAI_SIZES[request.plan.kind],
            "quality": self.quality,
            "background": background,
            "output_format": "png",
            "n": 1,
        }
        if request.reference is None:
            response = self.client.images.generate(**options)
        else:
            extension = "jpg" if request.reference.media_type == "image/jpeg" else "png"
            response = self.client.images.edit(
                image=(
                    f"reference.{extension}",
                    request.reference.content,
                    request.reference.media_type,
                ),
                **options,
            )
        if not response.data or not response.data[0].b64_json:
            raise RuntimeError("OpenAI image response did not contain image data")
        raw = base64.b64decode(response.data[0].b64_json)
        self.raw_outputs[request.plan.asset_id] = raw
        return postprocess(raw, request)


def _retry_moderation(call: Any) -> bytes:
    """Run ``call(suffix)`` with each moderation retry suffix until one passes."""

    blocked: Exception | None = None
    for suffix in MODERATION_RETRY_SUFFIXES:
        try:
            return call(suffix)
        except Exception as error:
            if getattr(error, "code", None) != "moderation_blocked":
                raise
            blocked = error
    raise RuntimeError(
        f"Blocked by the safety system after "
        f"{len(MODERATION_RETRY_SUFFIXES)} prompt variants: {blocked}"
    ) from blocked


LOCAL_BASE_URL_ENVIRONMENT_KEY = "MAINFLOW_LOCAL_IMAGE_BASE_URL"
# The team's LocalAI compose file sets LOCAL_LLM_BASE_URL for the mainflow
# service, so the image backend reuses it when no image-specific URL is given.
SHARED_LOCAL_BASE_URL_ENVIRONMENT_KEY = "LOCAL_LLM_BASE_URL"
DEFAULT_LOCAL_BASE_URL = "http://127.0.0.1:8080/v1"
LOCAL_MODEL_ENVIRONMENT_KEY = "MAINFLOW_LOCAL_IMAGE_MODEL"
LOCAL_API_KEY_ENVIRONMENT_KEY = "LOCAL_LLM_API_KEY"
LOCAL_SIZE_ENVIRONMENT_KEY = "MAINFLOW_LOCAL_IMAGE_SIZE"
DEFAULT_LOCAL_SIZE = "512x512"
LOCAL_STEPS_ENVIRONMENT_KEY = "MAINFLOW_LOCAL_IMAGE_STEPS"
LOCAL_TIMEOUT_ENVIRONMENT_KEY = "MAINFLOW_LOCAL_IMAGE_TIMEOUT_SECONDS"
# Local diffusion on a single GPU can take minutes per image.
DEFAULT_LOCAL_TIMEOUT_SECONDS = 600.0
# Diffusion models cannot output alpha, so sprites are drawn on a flat
# background that postprocess() removes afterwards.
LOCAL_FLAT_BACKGROUND_PROMPT = FLAT_BACKGROUND_PROMPT
SIZE_PATTERN = re.compile(r"^[1-9][0-9]*x[1-9][0-9]*$")


class LocalImageGenerator:
    """Generate images with a local OpenAI-compatible image server.

    Settings (environment):

    - ``MAINFLOW_LOCAL_IMAGE_MODEL``: required, e.g. ``flux.1-dev-ggml`` in LocalAI.
    - ``MAINFLOW_LOCAL_IMAGE_BASE_URL``: falls back to ``LOCAL_LLM_BASE_URL`` and
      then ``http://127.0.0.1:8080/v1``.
    - ``LOCAL_LLM_API_KEY``: optional, only if the server requires one.
    - ``MAINFLOW_LOCAL_IMAGE_SIZE``: generation size, default ``512x512``.
    - ``MAINFLOW_LOCAL_IMAGE_STEPS``: optional diffusion step count.
    - ``MAINFLOW_LOCAL_IMAGE_TIMEOUT_SECONDS``: default 600.

    A ``Custom`` reference image is not sent; the style comes from the prompt.
    """

    name = "local"

    def __init__(
        self,
        model: str | None = None,
        *,
        base_url: str | None = None,
        client: Any | None = None,
        size: str | None = None,
        steps: int | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self.model = (model or os.environ.get(LOCAL_MODEL_ENVIRONMENT_KEY) or "").strip()
        if not self.model:
            raise ValueError(
                f"Set {LOCAL_MODEL_ENVIRONMENT_KEY} to an image model installed on the local "
                "server (for example flux.1-dev-ggml in LocalAI). Text models such as "
                "Gemma cannot generate images."
            )
        self.base_url = (
            base_url
            or os.environ.get(LOCAL_BASE_URL_ENVIRONMENT_KEY)
            or os.environ.get(SHARED_LOCAL_BASE_URL_ENVIRONMENT_KEY)
            or DEFAULT_LOCAL_BASE_URL
        ).strip()
        self.size = (
            size or os.environ.get(LOCAL_SIZE_ENVIRONMENT_KEY) or DEFAULT_LOCAL_SIZE
        ).strip()
        if not SIZE_PATTERN.fullmatch(self.size):
            raise ValueError(
                f"{LOCAL_SIZE_ENVIRONMENT_KEY} must look like 512x512, got {self.size!r}"
            )
        steps_value = steps if steps is not None else os.environ.get(LOCAL_STEPS_ENVIRONMENT_KEY)
        self.steps = int(steps_value) if steps_value not in (None, "") else None
        if self.steps is not None and self.steps < 1:
            raise ValueError(f"{LOCAL_STEPS_ENVIRONMENT_KEY} must be at least 1")
        if timeout_seconds is None:
            timeout_seconds = float(
                os.environ.get(LOCAL_TIMEOUT_ENVIRONMENT_KEY) or DEFAULT_LOCAL_TIMEOUT_SECONDS
            )
        if client is None:
            from openai import OpenAI

            client = OpenAI(
                base_url=self.base_url,
                # The SDK requires a key even when the local server does not.
                api_key=os.environ.get(LOCAL_API_KEY_ENVIRONMENT_KEY) or "not-needed",
                timeout=timeout_seconds,
                max_retries=1,
            )
        self.client = client

    def generate(self, request: ImageRequest) -> bytes:
        prompt = request.prompt
        if request.plan.transparent:
            prompt += LOCAL_FLAT_BACKGROUND_PROMPT
        extra_body = {"step": self.steps} if self.steps is not None else None
        response = self.client.images.generate(
            model=self.model,
            prompt=prompt,
            size=self.size,
            response_format="b64_json",
            n=1,
            extra_body=extra_body,
        )
        if not response.data:
            raise RuntimeError("Local image server response did not contain image data")
        item = response.data[0]
        if getattr(item, "b64_json", None):
            content = base64.b64decode(item.b64_json)
        elif getattr(item, "url", None):
            # Some servers ignore response_format and return a file URL instead.
            content = _download(item.url)
        else:
            raise RuntimeError("Local image server response did not contain image data")
        return postprocess(content, request)


def _download(url: str, timeout_seconds: float = 60.0) -> bytes:
    if not url.startswith(("http://", "https://")):
        raise RuntimeError(f"Unsupported image URL from local server: {url!r}")
    with urllib.request.urlopen(url, timeout=timeout_seconds) as response:  # noqa: S310
        return response.read()


def create_image_generator(backend: str | None = None) -> ImageGenerator:
    backend = backend or os.environ.get(BACKEND_ENVIRONMENT_KEY) or "placeholder"
    backend = backend.strip().lower()
    if backend == "placeholder":
        return PlaceholderImageGenerator()
    if backend == "openai":
        return OpenAIImageGenerator()
    if backend == "local":
        return LocalImageGenerator()
    raise ValueError(
        f"Unsupported {BACKEND_ENVIRONMENT_KEY}: {backend!r} "
        "(expected 'placeholder', 'openai' or 'local')"
    )


# ---------------------------------------------------------------------------
# Post-processing
# ---------------------------------------------------------------------------
def postprocess(content: bytes, request: ImageRequest) -> bytes:
    """Resize, clean up and re-encode generator output to the planned asset."""

    with Image.open(io.BytesIO(content)) as source:
        image = source.convert("RGBA")

    if request.plan.transparent:
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

    width, height = image.size
    if width * height <= EXACT_FLOODFILL_MAX_PIXELS:
        return _floodfill_corners(image, threshold)

    # Pillow's floodfill runs per pixel in Python, which takes seconds on a
    # 1536x1024 strip.  Find the connected background on a reduced copy, then
    # keep only full-resolution pixels whose color is close to a corner color
    # so edges stay exact.
    factor = math.ceil(math.sqrt(width * height / EXACT_FLOODFILL_MAX_PIXELS))
    small = image.resize(
        (max(1, width // factor), max(1, height // factor)), Image.Resampling.NEAREST
    )
    connected = (
        _floodfill_corners(small, threshold)
        .getchannel("A")
        .point(lambda value: 255 if value == 0 else 0)
        .resize((width, height), Image.Resampling.NEAREST)
    )
    rgb = image.convert("RGB")
    close = Image.new("L", (width, height), 0)
    for corner in ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)):
        if image.getpixel(corner)[3] == 0:
            continue
        solid = Image.new("RGB", (width, height), image.getpixel(corner)[:3])
        difference = ImageChops.difference(rgb, solid).split()
        distance = ImageChops.lighter(
            ImageChops.lighter(difference[0], difference[1]), difference[2]
        )
        close = ImageChops.lighter(
            close, distance.point(lambda value: 255 if value <= threshold else 0)
        )
    remove = ImageChops.multiply(connected, close)
    result = image.copy()
    result.putalpha(ImageChops.subtract(image.getchannel("A"), remove))
    return result


def _floodfill_corners(image: Image.Image, threshold: int) -> Image.Image:
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

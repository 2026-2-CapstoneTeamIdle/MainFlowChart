"""OpenAI-compatible local image provider used by the node runner."""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from MCP.llm_config import LLMSettings
from MCP.llm_providers import LLMProviderError
from MCP.llm_types import ImageGenerationOptions

_SIZE_PATTERN = re.compile(r"^(?P<width>\d{2,4})x(?P<height>\d{2,4})$")
_FILENAME_PREFIX_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


@dataclass(frozen=True)
class GeneratedImageData:
    """Decoded image bytes returned by an image-generation endpoint."""

    content: bytes
    media_type: str
    extension: str


def validate_image_options(options: ImageGenerationOptions) -> None:
    """Reject values that LocalAI cannot safely persist or generate."""

    match = _SIZE_PATTERN.fullmatch(options.size)
    if match is None:
        raise ValueError("image size must use WIDTHxHEIGHT, for example 512x512")
    width = int(match.group("width"))
    height = int(match.group("height"))
    if width < 128 or height < 128 or width > 2048 or height > 2048:
        raise ValueError("image width and height must be between 128 and 2048")
    if options.count < 1 or options.count > 4:
        raise ValueError("image count must be between 1 and 4")
    if options.steps < 1 or options.steps > 50:
        raise ValueError("image steps must be between 1 and 50")
    if not _FILENAME_PREFIX_PATTERN.fullmatch(options.filename_prefix):
        raise ValueError("image filename_prefix must contain only letters, digits, '.', '_' or '-'")
    if options.artifact_category not in {"image", "validation"}:
        raise ValueError("generated images may only use the image or validation artifact category")


def _image_metadata(content: bytes, declared_media_type: str | None = None) -> tuple[str, str]:
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", ".png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", ".jpg"
    if content.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif", ".gif"
    if content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return "image/webp", ".webp"

    normalized = (declared_media_type or "").split(";", maxsplit=1)[0].strip().lower()
    extensions = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/gif": ".gif",
        "image/webp": ".webp",
    }
    if normalized in extensions:
        return normalized, extensions[normalized]
    raise LLMProviderError("Image provider returned an unsupported image format")


class LocalImageGenerationProvider:
    """Generate images through LocalAI's OpenAI-compatible image endpoint."""

    name = "local"

    def __init__(self, settings: LLMSettings) -> None:
        if settings.provider not in {"local", "vastai"}:
            raise ValueError("Image generation requires a local or Vast.ai provider")
        if settings.base_url is None:
            raise ValueError("Local image generation requires a base URL")
        self.name = settings.provider
        self.model = settings.model
        self._api_key = settings.api_key
        self._base_url = settings.base_url.rstrip("/")
        self._timeout_seconds = settings.timeout_seconds

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def _post_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self._base_url}/images/generations",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_seconds) as response:
                decoded = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            raise LLMProviderError(
                f"Local image request failed with HTTP status {error.code}"
            ) from None
        except urllib.error.URLError as error:
            raise LLMProviderError("Could not connect to the local image provider") from error
        except json.JSONDecodeError as error:
            raise LLMProviderError("Local image provider returned invalid JSON") from error
        if not isinstance(decoded, dict):
            raise LLMProviderError("Local image provider returned an invalid response")
        return decoded

    def _safe_image_url(self, returned_url: str) -> str:
        base = urllib.parse.urlsplit(self._base_url)
        candidate = urllib.parse.urlsplit(returned_url)
        if not candidate.scheme and not candidate.netloc:
            origin = f"{base.scheme}://{base.netloc}"
            return urllib.parse.urljoin(origin, returned_url)

        if candidate.scheme not in {"http", "https"}:
            raise LLMProviderError("Local image provider returned an unsupported image URL")
        if candidate.hostname in {"localhost", "127.0.0.1"} and base.hostname not in {
            "localhost",
            "127.0.0.1",
        }:
            return urllib.parse.urlunsplit(
                (base.scheme, base.netloc, candidate.path, candidate.query, "")
            )
        if (candidate.scheme, candidate.netloc) != (base.scheme, base.netloc):
            raise LLMProviderError("Local image provider returned an unexpected image origin")
        return returned_url

    def _download_image(self, returned_url: str) -> GeneratedImageData:
        request = urllib.request.Request(
            self._safe_image_url(returned_url),
            headers={key: value for key, value in self._headers().items() if key != "Content-Type"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_seconds) as response:
                content = response.read()
                declared_media_type = response.headers.get("Content-Type")
        except urllib.error.HTTPError as error:
            raise LLMProviderError(
                f"Local image download failed with HTTP status {error.code}"
            ) from None
        except urllib.error.URLError as error:
            raise LLMProviderError("Could not download the generated local image") from error
        media_type, extension = _image_metadata(content, declared_media_type)
        return GeneratedImageData(content, media_type, extension)

    @staticmethod
    def _decode_base64_image(value: str) -> GeneratedImageData:
        try:
            content = base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError) as error:
            raise LLMProviderError(
                "Local image provider returned invalid base64 image data"
            ) from error
        media_type, extension = _image_metadata(content)
        return GeneratedImageData(content, media_type, extension)

    def _generate(
        self, prompt: str, options: ImageGenerationOptions
    ) -> tuple[GeneratedImageData, ...]:
        validate_image_options(options)
        localai_prompt = prompt
        if options.negative_prompt:
            localai_prompt = f"{prompt}|{options.negative_prompt.strip()}"
        payload = {
            "model": self.model,
            "prompt": localai_prompt,
            "size": options.size,
            "n": options.count,
            "step": options.steps,
            "response_format": "b64_json",
        }
        response = self._post_json(payload)
        data = response.get("data")
        if not isinstance(data, list) or not data:
            raise LLMProviderError("Local image provider returned no images")

        images: list[GeneratedImageData] = []
        for item in data:
            if not isinstance(item, dict):
                raise LLMProviderError("Local image provider returned an invalid image item")
            encoded = item.get("b64_json")
            returned_url = item.get("url")
            if isinstance(encoded, str) and encoded:
                images.append(self._decode_base64_image(encoded))
            elif isinstance(returned_url, str) and returned_url:
                images.append(self._download_image(returned_url))
            else:
                raise LLMProviderError("Local image response has neither b64_json nor url")
        if len(images) != options.count:
            raise LLMProviderError(
                f"Local image provider returned {len(images)} images; expected {options.count}"
            )
        return tuple(images)

    async def generate(
        self,
        prompt: str,
        options: ImageGenerationOptions,
    ) -> tuple[GeneratedImageData, ...]:
        """Generate and decode all images without blocking the event loop."""

        return await asyncio.to_thread(self._generate, prompt, options)

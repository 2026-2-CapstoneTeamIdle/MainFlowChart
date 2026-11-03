"""Resolve role-specific Vast.ai vLLM endpoints without provisioning credentials."""

from __future__ import annotations

import os
import urllib.parse
from dataclasses import dataclass
from typing import Literal

VastAIRole = Literal["coder", "vlm", "image"]

_DEFAULTS: dict[VastAIRole, tuple[str, str]] = {
    "coder": ("http://127.0.0.1:18000/v1", "mainflow-coder"),
    "vlm": ("http://127.0.0.1:18001/v1", "mainflow-vlm"),
    "image": ("http://127.0.0.1:18002/v1", "mainflow-image"),
}


@dataclass(frozen=True)
class VastAISettings:
    """One OpenAI-compatible inference endpoint running on a Vast.ai instance."""

    role: VastAIRole
    base_url: str
    model: str
    api_key: str | None
    timeout_seconds: float
    context_tokens: int | None = None
    max_output_tokens: int | None = None


def load_vastai_settings(role: VastAIRole) -> VastAISettings:
    """Load one role while keeping the Vast account API key out of inference calls."""

    default_url, default_model = _DEFAULTS[role]
    prefix = f"VASTAI_{role.upper()}"
    base_url = os.environ.get(f"{prefix}_BASE_URL", default_url).strip().rstrip("/")
    parsed_url = urllib.parse.urlparse(base_url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        raise ValueError(f"{prefix}_BASE_URL must be an HTTP(S) OpenAI-compatible /v1 URL")

    model = os.environ.get(f"{prefix}_MODEL", default_model).strip()
    if not model:
        raise ValueError(f"{prefix}_MODEL must not be empty")

    timeout_seconds = float(os.environ.get("VASTAI_INFERENCE_TIMEOUT_SECONDS", "600"))
    if timeout_seconds <= 0:
        raise ValueError("VASTAI_INFERENCE_TIMEOUT_SECONDS must be greater than zero")

    context_tokens = None
    max_output_tokens = None
    if role == "coder":
        context_tokens = int(os.environ.get("VASTAI_CODER_CONTEXT_TOKENS", "32768"))
        max_output_tokens = int(os.environ.get("VASTAI_CODER_MAX_OUTPUT_TOKENS", "8192"))
        if max_output_tokens < 1024:
            raise ValueError("VASTAI_CODER_MAX_OUTPUT_TOKENS must be at least 1024")
        if context_tokens < max_output_tokens + 1024:
            raise ValueError(
                "VASTAI_CODER_CONTEXT_TOKENS must leave at least 1024 input tokens after output"
            )

    return VastAISettings(
        role=role,
        base_url=base_url,
        model=model,
        api_key=os.environ.get("VASTAI_INFERENCE_API_KEY") or None,
        timeout_seconds=timeout_seconds,
        context_tokens=context_tokens,
        max_output_tokens=max_output_tokens,
    )

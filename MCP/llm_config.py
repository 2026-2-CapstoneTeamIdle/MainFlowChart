"""Environment configuration for interchangeable LLM providers."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

SUPPORTED_LLM_PROVIDERS = ("gemini", "openai", "local")


def _normalize_provider(value: str) -> str:
    aliases = {
        "gemini": "gemini",
        "google": "gemini",
        "openai": "openai",
        "local": "local",
        "localslm": "local",
        "local_slm": "local",
        "ollama": "local",
    }
    normalized = aliases.get(value.strip().lower())
    if normalized is None:
        supported = ", ".join(SUPPORTED_LLM_PROVIDERS)
        raise ValueError(f"Unsupported LLM provider {value!r}; expected one of: {supported}")
    return normalized


def _node_environment_name(node_name: str, suffix: str) -> str:
    safe_name = re.sub(r"[^A-Za-z0-9]+", "_", node_name).strip("_").upper()
    return f"LLM_{safe_name}_{suffix}"


def _first_environment(*names: str, default: str | None = None) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value is not None and value.strip():
            return value.strip()
    return default


@dataclass(frozen=True)
class LLMSettings:
    """Resolved settings for one workflow node and one provider."""

    provider: str
    model: str
    api_key: str | None
    base_url: str | None
    timeout_seconds: float

    @classmethod
    def from_environment(
        cls,
        *,
        node_name: str,
        provider: str | None = None,
        model: str | None = None,
    ) -> LLMSettings:
        """Resolve explicit, node-specific, then global settings in that order."""

        provider_value = provider or _first_environment(
            _node_environment_name(node_name, "PROVIDER"),
            "LLM_PROVIDER",
            default="gemini",
        )
        if provider_value is None:
            raise RuntimeError("LLM provider resolution failed")
        normalized_provider = _normalize_provider(provider_value)

        provider_defaults = {
            "gemini": ("GEMINI_MODEL", "gemini-3-flash-preview"),
            "openai": ("OPENAI_MODEL", "gpt-4.1-mini"),
            "local": ("LOCAL_LLM_MODEL", "gemma3"),
        }
        provider_model_name, default_model = provider_defaults[normalized_provider]
        resolved_model = model or _first_environment(
            _node_environment_name(node_name, "MODEL"),
            "LLM_MODEL",
            provider_model_name,
            default=default_model,
        )
        if resolved_model is None:
            raise RuntimeError("LLM model resolution failed")

        key_names = {
            "gemini": ("GEMINI_API_KEY",),
            "openai": ("OPENAI_API_KEY",),
            "local": ("LOCAL_LLM_API_KEY",),
        }
        api_key = _first_environment(*key_names[normalized_provider])
        base_urls = {
            "gemini": None,
            "openai": _first_environment("OPENAI_BASE_URL", default="https://api.openai.com/v1"),
            "local": _first_environment("LOCAL_LLM_BASE_URL", default="http://127.0.0.1:11434/v1"),
        }
        timeout_value = _first_environment("LLM_TIMEOUT_SECONDS", default="120")
        if timeout_value is None:
            raise RuntimeError("LLM timeout resolution failed")
        timeout_seconds = float(timeout_value)
        if timeout_seconds <= 0:
            raise ValueError("LLM_TIMEOUT_SECONDS must be greater than zero")

        return cls(
            provider=normalized_provider,
            model=resolved_model,
            api_key=api_key,
            base_url=base_urls[normalized_provider],
            timeout_seconds=timeout_seconds,
        )

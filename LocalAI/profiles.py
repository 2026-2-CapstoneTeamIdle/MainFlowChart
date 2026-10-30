"""Named LocalAI profiles selectable from workflow nodes."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from MCP.llm_config import LLMSettings


@dataclass(frozen=True)
class LocalAIModelProfile:
    """Non-secret connection metadata for one LocalAI-served model."""

    provider: str
    model: str
    base_url_environment: str
    default_base_url: str
    api_key_environment: str | None = None
    allowed_nodes: frozenset[str] = frozenset()
    capabilities: frozenset[str] = frozenset({"text"})

    def settings(self, node_name: str, capability: str = "text") -> LLMSettings:
        """Resolve runtime values without storing credentials in the profile."""

        if self.allowed_nodes and node_name not in self.allowed_nodes:
            raise PermissionError(f"Node {node_name} cannot use LocalAI model profile {self.model}")
        if capability not in self.capabilities:
            raise ValueError(
                f"LocalAI model profile {self.model} does not support {capability!r} output"
            )

        api_key = None
        if self.api_key_environment is not None:
            api_key = os.environ.get(self.api_key_environment) or None
        base_url = os.environ.get(
            self.base_url_environment,
            self.default_base_url,
        ).strip()
        if not base_url:
            raise ValueError(f"{self.base_url_environment} must be a non-empty LocalAI URL")

        timeout_value = os.environ.get("LLM_TIMEOUT_SECONDS", "120")
        timeout_seconds = float(timeout_value)
        if timeout_seconds <= 0:
            raise ValueError("LLM_TIMEOUT_SECONDS must be greater than zero")

        return LLMSettings(
            provider=self.provider,
            model=self.model,
            api_key=api_key,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
        )


AI_MODEL_PROFILES: dict[str, LocalAIModelProfile] = {
    "qwen_coder_7b": LocalAIModelProfile(
        provider="local",
        model="qwen2.5-coder-7b-q5-k-m",
        base_url_environment="LOCAL_LLM_BASE_URL",
        default_base_url="http://127.0.0.1:8080/v1",
        api_key_environment="LOCAL_LLM_API_KEY",
    ),
    "gemma4_e2b_q4": LocalAIModelProfile(
        provider="local",
        model="gemma4-e2b-q4",
        base_url_environment="LOCAL_LLM_BASE_URL",
        default_base_url="http://127.0.0.1:8080/v1",
        api_key_environment="LOCAL_LLM_API_KEY",
    ),
    "gemma4_e4b": LocalAIModelProfile(
        provider="local",
        model="gemma4-e4b",
        base_url_environment="LOCAL_LLM_BASE_URL",
        default_base_url="http://127.0.0.1:8080/v1",
        api_key_environment="LOCAL_LLM_API_KEY",
    ),
    "sd_turbo": LocalAIModelProfile(
        provider="local",
        model="sd-turbo",
        base_url_environment="LOCAL_IMAGE_BASE_URL",
        default_base_url="http://127.0.0.1:8080/v1",
        api_key_environment="LOCAL_LLM_API_KEY",
        capabilities=frozenset({"image"}),
    ),
}


def _normalize_profile_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")


def resolve_ai_settings(
    profile_name: str,
    node_name: str,
    capability: str = "text",
) -> LLMSettings:
    """Resolve a friendly AI name to provider settings for the current node."""

    normalized_name = _normalize_profile_name(profile_name)
    try:
        profile = AI_MODEL_PROFILES[normalized_name]
    except KeyError as error:
        available = ", ".join(sorted(AI_MODEL_PROFILES))
        raise ValueError(
            f"Unknown AI model profile {profile_name!r}; available profiles: {available}"
        ) from error
    return profile.settings(node_name, capability)

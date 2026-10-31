"""Provider-neutral types used by the MCP-aware LLM runner."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, TypeAlias

from mainflow.contracts import ArtifactCategory, ArtifactReference
from MCP.manager import MCPToolDefinition


@dataclass(frozen=True)
class LLMToolCall:
    """One function call requested by an LLM provider."""

    call_id: str
    name: str
    arguments: dict[str, Any]


LLMContentBlock: TypeAlias = dict[str, Any]
LLMMessageContent: TypeAlias = str | list[LLMContentBlock]


@dataclass(frozen=True)
class LLMConversationMessage:
    """Small common message format translated by each provider adapter."""

    role: str
    # OpenAI-compatible providers accept multimodal content blocks here.  Text-only
    # callers keep using a plain string, so the existing node API remains unchanged.
    content: LLMMessageContent = ""
    tool_calls: tuple[LLMToolCall, ...] = ()
    tool_call_id: str | None = None
    tool_name: str | None = None
    tool_result: dict[str, Any] | None = None


@dataclass(frozen=True)
class LLMProviderResponse:
    """Normalized response returned by Gemini, OpenAI, or a local model."""

    text: str
    tool_calls: tuple[LLMToolCall, ...] = ()


@dataclass(frozen=True)
class LLMToolExecution:
    """Auditable MCP tool call made during one LLM run."""

    call_id: str
    name: str
    arguments: dict[str, Any]
    result: dict[str, Any]


@dataclass(frozen=True)
class LLMRunResult:
    """Final provider-independent value returned to a workflow node."""

    text: str
    provider: str
    model: str
    turns: int
    tool_calls: tuple[LLMToolExecution, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ImageGenerationOptions:
    """Options for the image branch of :func:`run_node_llm`."""

    size: str = "512x512"
    count: int = 1
    steps: int = 2
    negative_prompt: str | None = None
    filename_prefix: str = "generated_image"
    artifact_category: ArtifactCategory = "image"


@dataclass(frozen=True)
class ImageRunResult:
    """Workspace artifacts produced by a local image-generation model."""

    artifacts: tuple[ArtifactReference, ...]
    provider: str
    model: str
    prompt: str
    size: str


NodeRunOutput: TypeAlias = LLMRunResult | ImageRunResult
NodeOutputMode: TypeAlias = Literal["text", "image"]


class LLMProvider(Protocol):
    """Adapter interface implemented by every supported model provider."""

    name: str
    model: str

    async def complete(
        self,
        messages: list[LLMConversationMessage],
        tools: list[MCPToolDefinition],
        *,
        system_prompt: str | None,
        temperature: float,
        require_tool: bool,
        max_tokens: int | None = None,
    ) -> LLMProviderResponse:
        """Generate one assistant turn, possibly containing tool calls."""

    async def aclose(self) -> None:
        """Release provider-owned network resources."""

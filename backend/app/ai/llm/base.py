"""LLM provider abstraction.

Every generation call in the app (RAG answer synthesis, query rewriting,
future features) goes through this interface rather than calling the
Anthropic SDK directly, so the provider can be swapped via configuration —
see `app/ai/llm/factory.py`.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["user", "assistant"]
Effort = Literal["low", "medium", "high", "xhigh", "max"]


@dataclass(frozen=True, slots=True)
class LLMMessage:
    role: Role
    content: str


@dataclass(frozen=True, slots=True)
class LLMUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


@dataclass(frozen=True, slots=True)
class LLMResponse:
    content: str
    model: str
    stop_reason: str | None
    usage: LLMUsage = field(default_factory=LLMUsage)


@dataclass(frozen=True, slots=True)
class LLMToolDefinition:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True, slots=True)
class LLMToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class LLMToolMessage:
    role: Literal["user", "assistant", "tool"]
    content: str = ""
    tool_calls: list[LLMToolCall] = field(default_factory=list)
    tool_call_id: str | None = None
    tool_name: str | None = None


@dataclass(frozen=True, slots=True)
class LLMToolResponse:
    content: str
    model: str
    stop_reason: str | None
    tool_calls: list[LLMToolCall] = field(default_factory=list)
    usage: LLMUsage = field(default_factory=LLMUsage)
    server_timing_ns: dict[str, int] = field(default_factory=dict)


class LLMStream(ABC):
    """Handle returned by `LLMProvider.stream(...)`. Consume `text_stream` for
    incremental output, then call `get_final_response()` once the stream is
    exhausted to get the full text + usage."""

    @property
    @abstractmethod
    def text_stream(self) -> AsyncIterator[str]: ...

    @abstractmethod
    async def get_final_response(self) -> LLMResponse: ...


class LLMProvider(ABC):
    async def generate_with_tools(
        self,
        *,
        messages: list[LLMToolMessage],
        tools: list[LLMToolDefinition],
        system: str | None = None,
        max_tokens: int | None = None,
    ) -> LLMToolResponse:
        """Non-streaming tool protocol only; execution belongs to the caller."""
        raise NotImplementedError(f"{type(self).__name__} does not support Tool Calling")

    @abstractmethod
    async def generate(
        self,
        *,
        messages: list[LLMMessage],
        system: str | None = None,
        max_tokens: int | None = None,
        effort: Effort | None = None,
        enable_thinking: bool | None = None,
    ) -> LLMResponse:
        """Non-streaming generation — use for short, latency-tolerant calls
        (e.g. query rewriting). Prefer `stream()` for anything user-facing.

        `effort`/`enable_thinking` override the configured defaults
        (`LLM_EFFORT`/`LLM_ENABLE_THINKING`) for this call only — e.g. query
        rewriting wants `effort="low", enable_thinking=False` since it's a
        cheap, latency-sensitive task that doesn't benefit from either."""
        ...

    @abstractmethod
    def stream(
        self,
        *,
        messages: list[LLMMessage],
        system: str | None = None,
        max_tokens: int | None = None,
    ) -> AbstractAsyncContextManager[LLMStream]:
        """Usage: `async with provider.stream(...) as s: async for chunk in
        s.text_stream: ...`"""
        ...

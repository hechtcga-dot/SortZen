"""Provider-neutral request and reply types.

A request is a list of ``str`` and ``ImagePayload`` parts, in the order they are sent.
Every provider returns an ``AIResponse`` with the reply text and the token usage, which
the cost estimate and spending cap read.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Union


@dataclass(frozen=True)
class ImagePayload:
    data: bytes
    mime_type: str = "image/jpeg"


ContentPart = Union[str, ImagePayload]


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


@dataclass(frozen=True)
class AIResponse:
    text: str
    usage: TokenUsage = field(default_factory=TokenUsage)


class AIProvider:
    provider_name = "Unknown"

    def generate_json(self, model: str, contents: list[ContentPart]) -> AIResponse:
        raise NotImplementedError


def is_transient_api_error(exc: Exception) -> bool:
    text = f"{type(exc).__name__}: {exc}".lower()
    terms = (
        "429", "503", "resource_exhausted", "unavailable", "rate limit",
        "too many requests", "high demand", "temporar", "quota",
    )
    return any(t in text for t in terms)

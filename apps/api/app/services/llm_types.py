from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(slots=True)
class LLMUsage:
    prompt_tokens: int
    completion_tokens: int


@dataclass(slots=True)
class LLMResult:
    content: dict[str, object]
    model: str
    request_id: str | None
    usage: LLMUsage
    raw_content: str


@dataclass(slots=True)
class CostEstimate:
    amount_usd: Decimal
    prompt_tokens: int
    completion_tokens: int

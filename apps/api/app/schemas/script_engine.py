from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field


class ScriptEngineTestRequest(BaseModel):
    topic: str = Field(min_length=3, max_length=255)
    channel_slug: str = Field(default="internal-test", min_length=3, max_length=160)
    channel_name: str = Field(default="Internal Test", min_length=3, max_length=255)
    video_title: str | None = Field(default=None, max_length=255)


class ScriptEngineTestResponse(BaseModel):
    channel_id: int
    video_id: int
    script_id: int
    video_slug: str
    script_status: str
    policy_decision: str
    policy_risk_score: Decimal
    cache_hits: dict[str, bool]

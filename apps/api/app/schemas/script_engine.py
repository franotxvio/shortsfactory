from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.enums import VideoExecutionMode


class ScriptEngineTestRequest(BaseModel):
    topic: str = Field(min_length=3, max_length=255)
    channel_slug: str = Field(default="internal-test", min_length=3, max_length=160)
    channel_name: str = Field(default="Internal Test", min_length=3, max_length=255)
    video_title: str | None = Field(default=None, max_length=255)
    execution_mode: VideoExecutionMode = Field(default=VideoExecutionMode.FAKE)


class ScriptEngineTestResponse(BaseModel):
    channel_id: int
    video_id: int
    script_id: int
    video_slug: str
    script_status: str
    policy_decision: str
    policy_risk_score: Decimal
    cache_hits: dict[str, bool]
    hook: str | None = None
    body_blocks: list[str] | None = None
    call_to_action: str | None = None
    estimated_duration_seconds: int | None = None
    style_tone: str | None = None
    script_text: str | None = None

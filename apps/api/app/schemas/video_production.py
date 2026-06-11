from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import VideoExecutionMode


class VideoProductionRequest(BaseModel):
    auto_approve_preview: bool = Field(default=True)
    execution_mode: VideoExecutionMode = Field(default=VideoExecutionMode.FAKE)


class VideoProductionResponse(BaseModel):
    video_id: int
    audio_path: str
    caption_path: str
    preview_path: str
    final_path: str
    asset_path: str


class VideoCreateRequest(BaseModel):
    topic: str = Field(min_length=3, max_length=255)
    channel_slug: str = Field(default="internal-test", min_length=3, max_length=160)
    channel_name: str = Field(default="Internal Test", min_length=3, max_length=255)
    video_title: str | None = Field(default=None, max_length=255)
    execution_mode: VideoExecutionMode = Field(default=VideoExecutionMode.FAKE)


class VideoStepRequest(BaseModel):
    execution_mode: VideoExecutionMode = Field(default=VideoExecutionMode.FAKE)


class VideoPipelineResponse(BaseModel):
    video_id: int
    video_slug: str | None = None
    status: str
    stage_status: str
    script_id: int | None = None
    script_status: str | None = None
    asset_id: int | None = None
    audio_path: str | None = None
    caption_path: str | None = None
    preview_path: str | None = None
    final_path: str | None = None
    asset_path: str | None = None
    preview_approved_at: datetime | None = None


class VideoListResponse(BaseModel):
    items: list[VideoPipelineResponse]

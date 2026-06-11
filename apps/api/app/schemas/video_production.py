from __future__ import annotations

from datetime import datetime

from pydantic import AliasChoices
from pydantic import BaseModel, Field

from app.models.enums import VideoExecutionMode


class VideoProductionRequest(BaseModel):
    auto_approve_preview: bool = Field(default=True)
    execution_mode: VideoExecutionMode = Field(default=VideoExecutionMode.FAKE)
    visual_template: str = Field(default="default", max_length=64)


class VideoProductionResponse(BaseModel):
    video_id: int
    channel_slug: str | None = None
    audio_path: str
    caption_path: str
    preview_path: str
    final_path: str
    asset_path: str
    asset_name: str | None = None
    asset_slug: str | None = None
    asset_type: str | None = None
    asset_channel_slug: str | None = None
    asset_topic: str | None = None
    asset_tags: list[str] | None = None
    status: str | None = None
    stage_status: str | None = None
    is_demo: bool = False
    script_text: str | None = None
    hook: str | None = None
    body_blocks: list[str] | None = None
    call_to_action: str | None = None
    estimated_duration_seconds: int | None = None
    style_tone: str | None = None
    visual_template: str = "default"


class VideoCreateRequest(BaseModel):
    topic: str = Field(min_length=3, max_length=255)
    channel_slug: str = Field(default="internal-test", min_length=3, max_length=160)
    channel_name: str = Field(default="Internal Test", min_length=3, max_length=255)
    video_title: str | None = Field(default=None, max_length=255)
    execution_mode: VideoExecutionMode = Field(default=VideoExecutionMode.FAKE)


class VideoStepRequest(BaseModel):
    execution_mode: VideoExecutionMode = Field(default=VideoExecutionMode.FAKE)


class VideoPreviewRequest(BaseModel):
    visual_template: str = Field(default="default", max_length=64)


class VideoAssetSelectionRequest(BaseModel):
    asset_id: int | None = Field(default=None, ge=1)
    asset_slug: str | None = Field(default=None, max_length=160)
    channel_slug: str | None = Field(default=None, max_length=160)
    topic: str | None = Field(default=None, max_length=255)
    tags: list[str] | None = None


class AssetRegisterRequest(BaseModel):
    file_path: str = Field(min_length=1, max_length=1024, validation_alias=AliasChoices("file_path", "relative_path"))
    name: str | None = Field(default=None, max_length=255)
    slug: str | None = Field(default=None, max_length=160)
    asset_type: str | None = Field(default="background_image", max_length=64)
    license_name: str = Field(default="generated-local", max_length=128)
    license_url: str | None = Field(default=None, max_length=1024)
    channel_slug: str | None = Field(default=None, max_length=160)
    topic: str | None = Field(default=None, max_length=255)
    tags: list[str] | None = None


class AssetResponse(BaseModel):
    asset_id: int
    asset_type: str
    name: str
    slug: str
    source_path: str | None = None
    license_name: str
    license_url: str | None = None
    status: str
    channel_slug: str | None = None
    topic: str | None = None
    tags: list[str] | None = None
    is_default: bool = False


class AssetListResponse(BaseModel):
    items: list[AssetResponse]


class VideoScriptUpdateRequest(BaseModel):
    script_text: str = Field(min_length=3, max_length=10_000)
    hook: str | None = Field(default=None, max_length=2_000)
    body_blocks: list[str] | None = None
    call_to_action: str | None = Field(default=None, max_length=2_000)
    estimated_duration_seconds: int | None = Field(default=None, ge=1, le=3_600)
    style_tone: str | None = Field(default=None, max_length=255)


class VideoPipelineResponse(BaseModel):
    video_id: int
    video_slug: str | None = None
    channel_slug: str | None = None
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
    asset_name: str | None = None
    asset_slug: str | None = None
    asset_type: str | None = None
    asset_channel_slug: str | None = None
    asset_topic: str | None = None
    asset_tags: list[str] | None = None
    preview_approved_at: datetime | None = None
    is_demo: bool = False
    script_text: str | None = None
    hook: str | None = None
    body_blocks: list[str] | None = None
    call_to_action: str | None = None
    estimated_duration_seconds: int | None = None
    style_tone: str | None = None
    visual_template: str = "default"


class VideoListResponse(BaseModel):
    items: list[VideoPipelineResponse]

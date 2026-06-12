from __future__ import annotations

from datetime import datetime

from pydantic import AliasChoices
from pydantic import BaseModel, Field

from app.models.enums import VideoExecutionMode


class VideoProductionRequest(BaseModel):
    auto_approve_preview: bool = Field(default=True)
    execution_mode: VideoExecutionMode = Field(default=VideoExecutionMode.FAKE)
    visual_template: str = Field(default="default", max_length=64)


class YouTubePublishPrepRequest(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=10_000)
    tags: list[str] | None = None
    visibility: str = Field(default="private", max_length=32)
    made_for_kids: bool = Field(default=False)


class PublishReadinessCheckResponse(BaseModel):
    key: str
    label: str
    ready: bool
    value: str | None = None


class PublishReadinessResponse(BaseModel):
    video_id: int
    video_slug: str | None = None
    channel_slug: str | None = None
    stage_status: str | None = None
    overall_status: str
    ready: bool
    missing_items: list[str] = Field(default_factory=list)
    items: list[PublishReadinessCheckResponse] = Field(default_factory=list)


class VideoProductionResponse(BaseModel):
    video_id: int
    channel_slug: str | None = None
    target_duration_seconds: int | None = None
    video_title: str | None = None
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
    performance_label: str = "unknown"
    performance_notes: str | None = None
    performance_reason_tags: list[str] | None = None
    content_brain_context_used: bool = False
    winning_signals_count: int = 0
    weak_signals_count: int = 0
    applied_reason_tags: list[str] | None = None
    export_package_dir: str | None = None
    export_metadata_path: str | None = None
    export_final_path: str | None = None
    export_preview_path: str | None = None
    export_caption_path: str | None = None
    youtube_publish_path: str | None = None
    youtube_publish_title: str | None = None
    youtube_publish_description: str | None = None
    youtube_publish_tags: list[str] | None = None
    youtube_publish_visibility: str | None = None
    youtube_publish_made_for_kids: bool | None = None


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


class VideoPreviewRegenerateRequest(BaseModel):
    asset_id: int | None = Field(default=None, ge=1)
    visual_template: str | None = Field(default=None, max_length=64)


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
    target_duration_seconds: int | None = None
    video_title: str | None = None
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
    performance_label: str = "unknown"
    performance_notes: str | None = None
    performance_reason_tags: list[str] | None = None
    content_brain_context_used: bool = False
    winning_signals_count: int = 0
    weak_signals_count: int = 0
    applied_reason_tags: list[str] | None = None
    export_package_dir: str | None = None
    export_metadata_path: str | None = None
    export_final_path: str | None = None
    export_preview_path: str | None = None
    export_caption_path: str | None = None
    youtube_publish_path: str | None = None
    youtube_publish_title: str | None = None
    youtube_publish_description: str | None = None
    youtube_publish_tags: list[str] | None = None
    youtube_publish_visibility: str | None = None
    youtube_publish_made_for_kids: bool | None = None


class ChannelPresetUpsertRequest(BaseModel):
    channel_slug: str = Field(min_length=1, max_length=160)
    channel_name: str = Field(min_length=1, max_length=255)
    default_topic_style: str | None = Field(default=None, max_length=255)
    default_visual_template: str = Field(default="default", max_length=64)
    default_asset_slug: str | None = Field(default=None, max_length=160)
    default_cta: str | None = Field(default=None, max_length=2_000)
    target_duration_seconds: int | None = Field(default=None, ge=1, le=3_600)


class ChannelPresetResponse(BaseModel):
    channel_slug: str
    channel_name: str
    default_topic_style: str | None = None
    default_visual_template: str = "default"
    default_asset_slug: str | None = None
    default_cta: str | None = None
    target_duration_seconds: int | None = None


class ChannelPresetListResponse(BaseModel):
    items: list[ChannelPresetResponse]


class VideoJobEnqueueRequest(BaseModel):
    visual_template: str = Field(default="default", max_length=64)


class VideoJobResponse(BaseModel):
    job_id: str
    video_id: int
    job_type: str
    status: str
    error_message: str | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    visual_template: str | None = None


class VideoPerformanceUpdateRequest(BaseModel):
    performance_label: str = Field(default="unknown", max_length=32)
    notes: str | None = Field(default=None, max_length=10_000)
    reason_tags: list[str] | None = None


class VideoPerformanceResponse(BaseModel):
    video_id: int
    video_slug: str | None = None
    channel_slug: str | None = None
    topic: str | None = None
    performance_label: str = "unknown"
    notes: str | None = None
    reason_tags: list[str] | None = None
    updated_at: datetime | None = None


class VideoPerformanceListResponse(BaseModel):
    items: list[VideoPerformanceResponse]


class VideoListResponse(BaseModel):
    items: list[VideoPipelineResponse]

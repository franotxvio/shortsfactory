from __future__ import annotations

from pydantic import BaseModel, Field


class VideoProductionRequest(BaseModel):
    auto_approve_preview: bool = Field(default=True)


class VideoProductionResponse(BaseModel):
    video_id: int
    audio_path: str
    caption_path: str
    preview_path: str
    final_path: str
    asset_path: str

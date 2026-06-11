from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.models.core import Video
from app.models.enums import VideoStageStatus, WorkflowStatus
from app.services.media_utils import escape_ffmpeg_path, ensure_parent_dir, run_command


@dataclass(slots=True)
class RenderResult:
    video_id: int
    output_path: str


class RenderWorker:
    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()

    async def render_preview(self, *, video_id: int) -> RenderResult:
        video = await self._require_video_assets(video_id)
        output_path = self.settings.preview_output_path / f"{video.slug}.mp4"
        self._render(
            video=video,
            output_path=output_path,
            width=self.settings.preview_width,
            height=self.settings.preview_height,
            preset="veryfast",
        )
        video.preview_path = str(output_path)
        video.stage_status = VideoStageStatus.PREVIEW_READY
        await self.session.flush()
        return RenderResult(video_id=video.id, output_path=str(output_path))

    async def approve_preview(self, *, video_id: int) -> RenderResult:
        video = await self.session.get(Video, video_id)
        if video is None:
            raise ValueError(f"Video {video_id} not found")
        if not video.preview_path or not Path(video.preview_path).exists():
            raise ValueError("Preview must exist before approval")
        video.stage_status = VideoStageStatus.PREVIEW_APPROVED
        video.preview_approved_at = datetime.now(timezone.utc)
        await self.session.flush()
        return RenderResult(video_id=video.id, output_path=video.preview_path)

    async def render_final(self, *, video_id: int) -> RenderResult:
        video = await self._require_video_assets(video_id)
        if video.stage_status != VideoStageStatus.PREVIEW_APPROVED:
            raise ValueError("Preview must be approved before final render")
        output_path = self.settings.final_output_path / f"{video.slug}.mp4"
        self._render(
            video=video,
            output_path=output_path,
            width=self.settings.final_width,
            height=self.settings.final_height,
            preset="medium",
        )
        video.final_path = str(output_path)
        video.stage_status = VideoStageStatus.FINAL_RENDERED
        video.status = WorkflowStatus.COMPLETED
        await self.session.flush()
        return RenderResult(video_id=video.id, output_path=str(output_path))

    def _render(self, *, video: Video, output_path: Path, width: int, height: int, preset: str) -> None:
        if not video.asset or not video.asset.source_path:
            raise ValueError("Video asset is required before rendering")
        if not video.audio_path:
            raise ValueError("Audio is required before rendering")
        if not video.caption_path:
            raise ValueError("Captions are required before rendering")

        ensure_parent_dir(output_path)
        asset_path = Path(video.asset.source_path)
        caption_path = Path(video.caption_path)
        safe_margin_x = max(64, width // 12)
        safe_margin_y = max(120, height // 8)
        subtitle_font_size = 28 if width <= 720 else 34
        subtitle_margin_v = max(120, height // 9)
        filter_graph = (
            f"[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
            f"format=yuv420p,"
            f"subtitles='{escape_ffmpeg_path(caption_path)}':"
            f"force_style='FontName=Arial,FontSize={subtitle_font_size},Alignment=2,Outline=2,Shadow=0,"
            f"MarginV={subtitle_margin_v},MarginL={safe_margin_x},MarginR={safe_margin_x}'"
            "[v]"
        )
        command = [
            self.settings.ffmpeg_path,
            "-y",
            "-loop",
            "1",
            "-framerate",
            "30",
            "-i",
            str(asset_path),
            "-i",
            str(video.audio_path),
            "-filter_complex",
            filter_graph,
            "-map",
            "[v]",
            "-map",
            "1:a:0",
            "-c:v",
            "libx264",
            "-preset",
            preset,
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            "-shortest",
            str(output_path),
        ]
        run_command(command)

    async def _require_video_assets(self, video_id: int) -> Video:
        statement = select(Video).options(selectinload(Video.asset)).where(Video.id == video_id)
        video = await self.session.scalar(statement)
        if video is None:
            raise ValueError(f"Video {video_id} not found")
        if not video.audio_path:
            raise ValueError("Audio is required before rendering")
        if not video.caption_path:
            raise ValueError("Captions are required before rendering")
        if not video.asset_id:
            raise ValueError("Asset is required before rendering")
        return video

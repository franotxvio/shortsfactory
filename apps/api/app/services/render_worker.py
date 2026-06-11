from __future__ import annotations

import json
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

_VISUAL_TEMPLATES = {"default", "dark_overlay", "big_captions"}
_DEFAULT_VISUAL_TEMPLATE = "default"


@dataclass(slots=True)
class RenderResult:
    video_id: int
    output_path: str


class RenderWorker:
    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()

    async def render_preview(self, *, video_id: int, visual_template: str | None = None) -> RenderResult:
        video = await self._require_video_assets(video_id)
        resolved_template = self._resolve_visual_template_choice(
            video_id=video.id,
            current_stage=video.stage_status,
            requested_template=visual_template,
        )
        output_path = self.settings.preview_output_path / f"{video.slug}.mp4"
        self._render(
            video=video,
            output_path=output_path,
            width=self.settings.preview_width,
            height=self.settings.preview_height,
            preset="veryfast",
            visual_template=resolved_template,
        )
        self._write_visual_template(video_id=video.id, visual_template=resolved_template)
        video.preview_path = str(output_path)
        video.stage_status = VideoStageStatus.PREVIEW_READY
        await self.session.flush()
        return RenderResult(video_id=video.id, output_path=str(output_path))

    async def regenerate_preview(self, *, video_id: int, visual_template: str | None = None) -> RenderResult:
        video = await self._require_video_assets(video_id)
        if video.stage_status == VideoStageStatus.FINAL_RENDERED:
            raise ValueError("Preview cannot be regenerated after final render")

        if visual_template is None:
            resolved_template = self.get_visual_template(video_id)
        else:
            resolved_template = self._normalize_visual_template(visual_template)

        output_path = self.settings.preview_output_path / f"{video.slug}.mp4"
        self._render(
            video=video,
            output_path=output_path,
            width=self.settings.preview_width,
            height=self.settings.preview_height,
            preset="veryfast",
            visual_template=resolved_template,
        )
        self._write_visual_template(video_id=video.id, visual_template=resolved_template)
        video.preview_path = str(output_path)
        video.preview_approved_at = None
        video.stage_status = VideoStageStatus.PREVIEW_READY
        await self.session.flush()
        return RenderResult(video_id=video.id, output_path=str(output_path))

    def set_visual_template(self, *, video_id: int, visual_template: str) -> None:
        self._write_visual_template(video_id=video_id, visual_template=visual_template)

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
        visual_template = self.get_visual_template(video_id)
        self._render(
            video=video,
            output_path=output_path,
            width=self.settings.final_width,
            height=self.settings.final_height,
            preset="medium",
            visual_template=visual_template,
        )
        video.final_path = str(output_path)
        video.stage_status = VideoStageStatus.FINAL_RENDERED
        video.status = WorkflowStatus.COMPLETED
        await self.session.flush()
        return RenderResult(video_id=video.id, output_path=str(output_path))

    def get_visual_template(self, video_id: int) -> str:
        template_path = self._visual_template_path(video_id)
        if not template_path.exists():
            return _DEFAULT_VISUAL_TEMPLATE

        try:
            payload = json.loads(template_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return _DEFAULT_VISUAL_TEMPLATE

        if isinstance(payload, dict):
            stored_template = payload.get("visual_template")
            if isinstance(stored_template, str) and stored_template.strip():
                return self._normalize_visual_template(stored_template)
        return _DEFAULT_VISUAL_TEMPLATE

    def _render(
        self,
        *,
        video: Video,
        output_path: Path,
        width: int,
        height: int,
        preset: str,
        visual_template: str = _DEFAULT_VISUAL_TEMPLATE,
    ) -> None:
        if not video.asset or not video.asset.source_path:
            raise ValueError("Video asset is required before rendering")
        if not video.audio_path:
            raise ValueError("Audio is required before rendering")
        if not video.caption_path:
            raise ValueError("Captions are required before rendering")

        ensure_parent_dir(output_path)
        asset_path = Path(video.asset.source_path)
        if asset_path.suffix.lower() == ".mp4":
            raise ValueError("Background video assets (.mp4) are not supported yet")
        caption_path = Path(video.caption_path)
        safe_margin_x = max(64, width // 12)
        template = self._normalize_visual_template(visual_template)
        subtitle_font_size, subtitle_margin_v, add_overlay = self._visual_template_params(
            template=template,
            width=width,
            height=height,
        )
        filter_graph = self._build_filter_graph(
            caption_path=caption_path,
            width=width,
            height=height,
            subtitle_font_size=subtitle_font_size,
            subtitle_margin_v=subtitle_margin_v,
            safe_margin_x=safe_margin_x,
            add_overlay=add_overlay,
        )
        command = self._build_render_command(
            asset_path=asset_path,
            audio_path=Path(video.audio_path),
            filter_graph=filter_graph,
            output_path=output_path,
            preset=preset,
        )
        run_command(command)

    def _build_render_command(
        self,
        *,
        asset_path: Path,
        audio_path: Path,
        filter_graph: str,
        output_path: Path,
        preset: str,
    ) -> list[str]:
        return [
            self.settings.ffmpeg_path,
            "-y",
            "-loop",
            "1",
            "-framerate",
            "30",
            "-i",
            str(asset_path),
            "-i",
            str(audio_path),
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

    def _build_filter_graph(
        self,
        *,
        caption_path: Path,
        width: int,
        height: int,
        subtitle_font_size: int,
        subtitle_margin_v: int,
        safe_margin_x: int,
        add_overlay: bool,
    ) -> str:
        video_chain = (
            f"[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
        )
        if add_overlay:
            video_chain += ",format=rgba[bg];"
            video_chain += f"color=c=black@0.32:s={width}x{height}:d=1[overlay];"
            video_chain += "[bg][overlay]overlay=format=auto,format=yuv420p"
        else:
            video_chain += ",format=yuv420p"

        return (
            f"{video_chain},"
            f"subtitles='{escape_ffmpeg_path(caption_path)}':"
            f"force_style='FontName=Arial,FontSize={subtitle_font_size},Alignment=2,Outline=2,Shadow=0,"
            f"MarginV={subtitle_margin_v},MarginL={safe_margin_x},MarginR={safe_margin_x}'"
            "[v]"
        )

    def _visual_template_params(self, *, template: str, width: int, height: int) -> tuple[int, int, bool]:
        base_font_size = 28 if width <= 720 else 34
        base_margin_v = max(120, height // 9)
        if template == "dark_overlay":
            return base_font_size + 2, base_margin_v + 8, True
        if template == "big_captions":
            return base_font_size + 10, base_margin_v + 18, False
        return base_font_size, base_margin_v, False

    def _normalize_visual_template(self, value: str) -> str:
        template = value.strip().lower()
        if template not in _VISUAL_TEMPLATES:
            raise ValueError(
                "Unknown visual template. Allowed values: default, dark_overlay, big_captions"
            )
        return template

    def _resolve_visual_template_choice(
        self,
        *,
        video_id: int,
        current_stage: VideoStageStatus,
        requested_template: str | None,
    ) -> str:
        current_template = self.get_visual_template(video_id)
        if requested_template is None:
            resolved_template = current_template
        else:
            resolved_template = self._normalize_visual_template(requested_template)

        if current_stage in {
            VideoStageStatus.PREVIEW_READY,
            VideoStageStatus.PREVIEW_APPROVED,
            VideoStageStatus.FINAL_RENDERED,
        } and resolved_template != current_template:
            raise ValueError("Visual template can only be changed before preview is generated")
        return resolved_template

    def _visual_template_path(self, video_id: int) -> Path:
        return self.settings.local_storage_path / "renders" / "visual-templates" / f"{video_id}.json"

    def _write_visual_template(self, *, video_id: int, visual_template: str) -> None:
        template_path = self._visual_template_path(video_id)
        ensure_parent_dir(template_path)
        template_path.write_text(
            json.dumps({"visual_template": self._normalize_visual_template(visual_template)}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

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

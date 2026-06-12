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
from app.services.media_utils import escape_ffmpeg_path, ensure_parent_dir, probe_duration_seconds, run_command

_VISUAL_TEMPLATES = {"default", "dark_overlay", "big_captions", "viral_reels", "football_quiz", "general_quiz", "would_you_rather"}
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
        template = self._normalize_visual_template(visual_template)
        channel_slug = video.channel.slug.lower() if video.channel is not None and video.channel.slug else None
        safe_margin_x = max(64, width // 12)
        if template == "viral_reels":
            safe_margin_x = max(42, width // 20)
        if template in {"football_quiz", "general_quiz", "would_you_rather"}:
            safe_margin_x = max(48, width // 18)
        if channel_slug == "english-dev-shorts":
            safe_margin_x = max(38, width // 22)
        video_duration_seconds = probe_duration_seconds(Path(video.audio_path)) or float(video.target_duration_seconds or 0) or 10.0
        subtitle_font_size, subtitle_margin_v, add_overlay, use_zoompan, use_progress_bar, use_box_style = self._visual_template_params(
            template=template,
            width=width,
            height=height,
        )
        filter_graph = self._build_filter_graph(
            caption_path=caption_path,
            width=width,
            height=height,
            video_duration_seconds=video_duration_seconds,
            subtitle_font_size=subtitle_font_size,
            subtitle_margin_v=subtitle_margin_v,
            safe_margin_x=safe_margin_x,
            add_overlay=add_overlay,
            use_zoompan=use_zoompan,
            use_progress_bar=use_progress_bar,
            use_box_style=use_box_style,
            template=template,
            channel_slug=channel_slug,
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
        video_duration_seconds: float,
        subtitle_font_size: int,
        subtitle_margin_v: int,
        safe_margin_x: int,
        add_overlay: bool,
        use_zoompan: bool,
        use_progress_bar: bool,
        use_box_style: bool,
        template: str = _DEFAULT_VISUAL_TEMPLATE,
        channel_slug: str | None = None,
    ) -> str:
        if use_zoompan:
            video_chain = (
                f"[0:v]zoompan=z='min(1.10,1+0.00045*on)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                f"d=1:s={width}x{height}:fps=30"
            )
        else:
            video_chain = (
                f"[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
            )
        if channel_slug == "english-dev-shorts":
            video_chain += ",eq=brightness=-0.04:contrast=1.12:saturation=1.18"
            video_chain += ",drawgrid=width=96:height=96:thickness=1:color=0x22d3ee@0.10"
            video_chain += ",drawbox=x=0:y=0:w=iw:h=ih:color=0x07111b@0.14:t=fill"
        if add_overlay:
            video_chain += ",format=rgba[bg];"
            overlay_opacity = "0.40" if use_zoompan else "0.32"
            video_chain += f"color=c=black@{overlay_opacity}:s={width}x{height}:d=1[overlay];"
            video_chain += "[bg][overlay]overlay=format=auto,format=yuv420p"
        else:
            video_chain += ",format=yuv420p"

        if use_progress_bar:
            progress_width = f"if(lte(t\\,{video_duration_seconds:.3f})\\,{width}*t/{video_duration_seconds:.3f}\\,{width})"
            video_chain += f",drawbox=x=0:y=0:w={width}:h=18:color=black@0.10:t=fill"
            video_chain += f",drawbox=x=0:y=0:w='{progress_width}':h=8:color=0x22c55e@0.92:t=fill"

        template_overlay = self._template_overlay_chain(template=template, width=width, height=height)
        if template_overlay:
            video_chain += template_overlay

        if use_box_style:
            subtitles_style = (
                "FontName=Arial,FontSize="
                f"{subtitle_font_size},Alignment=2,Outline=2,BorderStyle=3,BackColour=&HAA101418,"
                f"PrimaryColour=&H00FFFFFF,Bold=1,Shadow=0,MarginV={subtitle_margin_v},MarginL={safe_margin_x},"
                f"MarginR={safe_margin_x}"
            )
        else:
            subtitles_style = (
                "FontName=Arial,FontSize="
                f"{subtitle_font_size},Alignment=2,Outline=2,Shadow=0,MarginV={subtitle_margin_v},"
                f"MarginL={safe_margin_x},MarginR={safe_margin_x}"
            )
        return (
            f"{video_chain},"
            f"subtitles='{escape_ffmpeg_path(caption_path)}':"
            f"force_style='{subtitles_style}'"
            "[v]"
        )

    def _visual_template_params(self, *, template: str, width: int, height: int) -> tuple[int, int, bool, bool, bool, bool]:
        base_font_size = 28 if width <= 720 else 34
        base_margin_v = max(120, height // 9)
        if template == "dark_overlay":
            return base_font_size + 2, base_margin_v + 8, True, False, False, False
        if template == "big_captions":
            return base_font_size + 10, base_margin_v + 18, False, False, False, True
        if template == "viral_reels":
            return 24, max(64, height // 22), True, True, True, True
        if template == "football_quiz":
            return 22, max(82, height // 18), True, True, True, True
        if template == "general_quiz":
            return 22, max(78, height // 20), True, False, True, True
        if template == "would_you_rather":
            return 22, max(84, height // 20), True, False, True, True
        return base_font_size, base_margin_v, False, False, False, False

    def _template_overlay_chain(self, *, template: str, width: int, height: int) -> str:
        if template == "football_quiz":
            return (
                ",drawbox=x=36:y=40:w=iw-72:h=132:color=0x081b13@0.68:t=fill"
                ",drawbox=x=54:y=58:w=260:h=40:color=0x22c55e@0.88:t=fill"
                ",drawbox=x=iw-314:y=58:w=260:h=40:color=0xf59e0b@0.88:t=fill"
                ",drawtext=text='FOOTBALL QUIZ':fontcolor=white:fontsize=28:x=74:y=66"
                ",drawtext=text='SCOREBOARD':fontcolor=white:fontsize=22:x=w-290:y=66"
                ",drawbox=x=44:y=ih-210:w=iw-88:h=168:color=0x07111b@0.42:t=fill"
                ",drawtext=text='REVEAL CARD':fontcolor=white:fontsize=24:x=(w-text_w)/2:y=h-194"
            )
        if template == "general_quiz":
            return (
                ",drawbox=x=46:y=42:w=iw-92:h=128:color=0x10182d@0.70:t=fill"
                ",drawtext=text='GENERAL QUIZ':fontcolor=0x93c5fd:fontsize=28:x=(w-text_w)/2:y=68"
                ",drawbox=x=56:y=156:w=iw-112:h=132:color=0x111827@0.52:t=fill"
                ",drawtext=text='CLUE CARD':fontcolor=white:fontsize=22:x=82:y=184"
                ",drawbox=x=44:y=ih-220:w=iw-88:h=174:color=0x0f172a@0.46:t=fill"
                ",drawtext=text='ANSWER REVEAL':fontcolor=white:fontsize=24:x=(w-text_w)/2:y=h-198"
            )
        if template == "would_you_rather":
            return (
                ",drawbox=x=44:y=44:w=iw-88:h=120:color=0x18181b@0.72:t=fill"
                ",drawtext=text='WOULD YOU RATHER':fontcolor=white:fontsize=26:x=(w-text_w)/2:y=68"
                ",drawbox=x=52:y=170:w=(iw-114)/2:h=238:color=0x2563eb@0.42:t=fill"
                ",drawbox=x=iw/2+10:y=170:w=(iw-114)/2:h=238:color=0xf97316@0.42:t=fill"
                ",drawtext=text='A':fontcolor=white:fontsize=36:x=96:y=198"
                ",drawtext=text='B':fontcolor=white:fontsize=36:x=w/2+54:y=198"
                ",drawbox=x=44:y=ih-210:w=iw-88:h=168:color=0x09090b@0.40:t=fill"
                ",drawtext=text='PICK A SIDE':fontcolor=white:fontsize=24:x=(w-text_w)/2:y=h-192"
            )
        return ""

    def _normalize_visual_template(self, value: str) -> str:
        template = value.strip().lower()
        if template not in _VISUAL_TEMPLATES:
            raise ValueError(
                "Unknown visual template. Allowed values: default, dark_overlay, big_captions, viral_reels, football_quiz, general_quiz, would_you_rather"
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
        statement = select(Video).options(selectinload(Video.asset), selectinload(Video.channel)).where(Video.id == video_id)
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

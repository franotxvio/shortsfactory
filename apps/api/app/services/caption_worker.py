from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.models.core import Script, Video
from app.models.enums import VideoStageStatus, WorkflowStatus
from app.services.media_utils import (
    build_srt_from_text,
    ensure_parent_dir,
    estimate_duration_from_text,
    escape_ffmpeg_path,
    probe_duration_seconds,
    run_command,
    write_text_file,
)


@dataclass(slots=True)
class CaptionResult:
    video_id: int
    caption_path: str
    used_whisper: bool


class CaptionWorker:
    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()

    async def generate(self, *, video_id: int) -> CaptionResult:
        video = await self.session.get(Video, video_id)
        if video is None:
            raise ValueError(f"Video {video_id} not found")
        if not video.audio_path:
            raise ValueError("Audio must be generated before captions")

        script = await self._get_approved_script(video_id)
        caption_path = self.settings.caption_output_path / f"{video.slug}.srt"
        ensure_parent_dir(caption_path)

        used_whisper = False
        if self.settings.whisper_model_path.exists():
            try:
                self._generate_with_whisper(Path(video.audio_path), caption_path)
                used_whisper = True
            except Exception:
                used_whisper = False

        if not used_whisper:
            duration = probe_duration_seconds(Path(video.audio_path)) or estimate_duration_from_text(script.content)
            srt = build_srt_from_text(script.content, duration)
            write_text_file(caption_path, srt)

        video.caption_path = str(caption_path)
        video.stage_status = VideoStageStatus.CAPTION_DONE
        await self.session.flush()

        return CaptionResult(video_id=video.id, caption_path=str(caption_path), used_whisper=used_whisper)

    def _generate_with_whisper(self, audio_path: Path, caption_path: Path) -> None:
        model_path = escape_ffmpeg_path(self.settings.whisper_model_path)
        destination = escape_ffmpeg_path(caption_path)
        command = [
            self.settings.ffmpeg_path,
            "-y",
            "-i",
            str(audio_path),
            "-af",
            f"whisper=model={model_path}:language=auto:destination='{destination}':format=srt",
            "-f",
            "null",
            "-",
        ]
        run_command(command)

    async def _get_approved_script(self, video_id: int) -> Script:
        statement = (
            select(Script)
            .where(Script.video_id == video_id, Script.status == WorkflowStatus.APPROVED)
            .order_by(Script.version.desc())
        )
        script = await self.session.scalar(statement)
        if script is None:
            raise ValueError("Approved script is required before captions")
        return script

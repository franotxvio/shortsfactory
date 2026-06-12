from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.models.core import Script, Video
from app.models.enums import VideoStageStatus, WorkflowStatus
from app.services.content_format_engine import normalize_content_format
from app.services.media_utils import (
    build_srt_from_text,
    build_srt_from_segments,
    ensure_parent_dir,
    estimate_duration_from_text,
    escape_ffmpeg_path,
    probe_duration_seconds,
    run_command,
    wrap_caption_text,
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

    async def generate(self, *, video_id: int, use_whisper: bool | None = None) -> CaptionResult:
        video = await self.session.get(Video, video_id)
        if video is None:
            raise ValueError(f"Video {video_id} not found")
        if not video.audio_path:
            raise ValueError("Audio must be generated before captions")

        script = await self._get_approved_script(video_id)
        caption_path = self.settings.caption_output_path / f"{video.slug}.srt"
        ensure_parent_dir(caption_path)

        used_whisper = False
        should_try_whisper = self.settings.whisper_model_path.exists() if use_whisper is None else use_whisper
        if should_try_whisper:
            try:
                self._generate_with_whisper(Path(video.audio_path), caption_path)
                used_whisper = True
            except Exception:
                used_whisper = False

        if not used_whisper:
            duration = probe_duration_seconds(Path(video.audio_path)) or estimate_duration_from_text(script.content)
            segments = self._extract_caption_segments(script)
            if segments:
                srt = build_srt_from_segments(segments, duration)
            else:
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

    def _extract_caption_segments(self, script: Script) -> list[str]:
        generation_payload = script.generation_payload if isinstance(script.generation_payload, dict) else {}
        script_payload = generation_payload.get("script") if isinstance(generation_payload.get("script"), dict) else {}
        style_tone = str(script_payload.get("style_tone") or "").strip().lower()
        estimated_duration_seconds = script_payload.get("estimated_duration_seconds")
        language = str(
            script_payload.get("language")
            or generation_payload.get("language")
            or generation_payload.get("language_code")
            or ""
        ).strip().lower()
        content_format = normalize_content_format(
            str(
                script_payload.get("content_format")
                or generation_payload.get("content_format")
                or generation_payload.get("format")
                or ""
            )
        )
        is_viral = style_tone == "viral_micro_short" or content_format is not None or (
            isinstance(estimated_duration_seconds, int) and 0 < estimated_duration_seconds <= 15
        )
        if not is_viral:
            return []

        segments: list[str] = []
        hook = str(script_payload.get("hook") or script.hook or "").strip()
        if hook:
            segments.append(hook)
        body_blocks = script_payload.get("body_blocks")
        if isinstance(body_blocks, list):
            for block in body_blocks:
                text = str(block).strip()
                if text:
                    segments.append(text)
        call_to_action = str(script_payload.get("call_to_action") or script_payload.get("cta") or "").strip()
        if call_to_action:
            segments.append(call_to_action)
        max_line_length = 28 if language in {"en", "en-us", "en-gb", "english"} else 30
        return [wrap_caption_text(segment, max_line_length=max_line_length, max_lines=2) for segment in segments]

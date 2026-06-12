from __future__ import annotations

import json
import hashlib
import re
import unicodedata
import shutil
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.models.core import AssetPool, Channel, Script, Video
from app.models.enums import LifecycleStatus, VideoExecutionMode, VideoStageStatus, WorkflowStatus
from app.services.content_brain import ContentBrainService
from app.services.asset_pool_service import AssetPoolService
from app.services.caption_worker import CaptionWorker
from app.services.media_utils import build_deterministic_mp3_bytes
from app.services.render_worker import RenderWorker
from app.services.script_engine import (
    ScriptEngineService,
    _build_consolidated_script_text,
    _VIRAL_MICRO_SHORT_DEFAULT_DURATION_SECONDS,
    _VIRAL_MICRO_SHORT_MAX_DURATION_SECONDS,
    _VIRAL_MICRO_SHORT_STYLE,
    _is_viral_micro_short_mode,
    _viral_micro_short_body_blocks,
    _viral_micro_short_hook,
)
from app.services.tts_worker import TTSWorker


_CHANNEL_PRESET_ALLOWED_TEMPLATES = {"default", "dark_overlay", "big_captions", "viral_reels"}


@dataclass(slots=True)
class ChannelPresetRecord:
    channel_slug: str
    channel_name: str
    default_topic_style: str | None = None
    default_visual_template: str = "default"
    default_asset_slug: str | None = None
    default_cta: str | None = None
    target_duration_seconds: int | None = None


@dataclass(slots=True)
class VideoProductionResult:
    video_id: int
    audio_path: str
    caption_path: str
    preview_path: str
    final_path: str
    asset_path: str
    channel_slug: str | None = None
    video_title: str | None = None
    asset_name: str | None = None
    asset_slug: str | None = None
    asset_type: str | None = None
    asset_channel_slug: str | None = None
    asset_topic: str | None = None
    asset_tags: list[str] | None = None
    hook: str | None = None
    body_blocks: list[str] | None = None
    call_to_action: str | None = None
    estimated_duration_seconds: int | None = None
    style_tone: str | None = None
    visual_template: str = "default"
    target_duration_seconds: int | None = None
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


@dataclass(slots=True)
class VideoPipelineState:
    video_id: int
    video_slug: str | None
    channel_slug: str | None
    status: str
    stage_status: str
    video_title: str | None = None
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
    script_text: str | None = None
    hook: str | None = None
    body_blocks: list[str] | None = None
    call_to_action: str | None = None
    estimated_duration_seconds: int | None = None
    style_tone: str | None = None
    visual_template: str = "default"
    target_duration_seconds: int | None = None
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


class _DeterministicTTSClient:
    def __init__(self, settings: Settings, *, duration_seconds: float = 2.0) -> None:
        self._settings = settings
        self._duration_seconds = duration_seconds
        self._audio_bytes: bytes | None = None

    async def generate_tts_audio(self, *, text: str, model: str, voice: str) -> tuple[bytes, str]:
        if self._audio_bytes is None:
            self._audio_bytes = build_deterministic_mp3_bytes(
                ffmpeg_path=self._settings.ffmpeg_path,
                duration_seconds=self._duration_seconds,
            )
        return self._audio_bytes, "local-fake-tts"


class VideoProductionService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings | None = None,
        tts_worker: TTSWorker | None = None,
        caption_worker: CaptionWorker | None = None,
        asset_service: AssetPoolService | None = None,
        content_brain_service: ContentBrainService | None = None,
        render_worker: RenderWorker | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self._provided_tts_worker = tts_worker
        self.tts_worker = tts_worker or TTSWorker(session, settings=self.settings)
        self.caption_worker = caption_worker or CaptionWorker(session, settings=self.settings)
        self.asset_service = asset_service or AssetPoolService(session, settings=self.settings)
        self.content_brain_service = content_brain_service or ContentBrainService(session, settings=self.settings)
        self.render_worker = render_worker or RenderWorker(session, settings=self.settings)

    async def produce_full_video(
        self,
        *,
        video_id: int,
        auto_approve_preview: bool = True,
        visual_template: str | None = None,
    ) -> VideoProductionResult:
        statement = select(Video.status, Video.stage_status).where(Video.id == video_id)
        row = (await self.session.execute(statement)).one_or_none()
        if row is None:
            raise ValueError(f"Video {video_id} not found")
        current_status, current_stage_status = row
        if current_stage_status == VideoStageStatus.FINAL_RENDERED or current_status == WorkflowStatus.COMPLETED:
            current_state = await self.get_status(video_id=video_id)
            return self._build_production_result_from_state(current_state)

        tts_result = await self.run_tts(video_id=video_id, execution_mode=VideoExecutionMode.FAKE)
        caption_result = await self.generate_captions(video_id=video_id, execution_mode=VideoExecutionMode.FAKE)
        asset_result = await self.select_asset(video_id=video_id)
        preview_result = await self.render_preview(video_id=video_id, visual_template=visual_template)
        if auto_approve_preview:
            await self.approve_preview(video_id=video_id)
        final_result = await self.render_final(video_id=video_id)
        final_state = await self.get_status(video_id=video_id)
        return VideoProductionResult(
            video_id=video_id,
            channel_slug=final_state.channel_slug,
            video_title=final_state.video_title,
            audio_path=tts_result.audio_path,
            caption_path=caption_result.caption_path,
            preview_path=preview_result.output_path,
            final_path=final_result.output_path,
            asset_path=final_state.asset_path or asset_result.asset_path,
            asset_name=final_state.asset_name,
            asset_slug=final_state.asset_slug,
            asset_type=final_state.asset_type,
            asset_channel_slug=final_state.asset_channel_slug,
            asset_topic=final_state.asset_topic,
            asset_tags=final_state.asset_tags,
            hook=final_state.hook,
            body_blocks=final_state.body_blocks,
            call_to_action=final_state.call_to_action,
            estimated_duration_seconds=final_state.estimated_duration_seconds,
            style_tone=final_state.style_tone,
            target_duration_seconds=final_state.target_duration_seconds,
            content_brain_context_used=final_state.content_brain_context_used,
            winning_signals_count=final_state.winning_signals_count,
            weak_signals_count=final_state.weak_signals_count,
            applied_reason_tags=final_state.applied_reason_tags,
            youtube_publish_path=final_state.youtube_publish_path,
            youtube_publish_title=final_state.youtube_publish_title,
            youtube_publish_description=final_state.youtube_publish_description,
            youtube_publish_tags=final_state.youtube_publish_tags,
            youtube_publish_visibility=final_state.youtube_publish_visibility,
            youtube_publish_made_for_kids=final_state.youtube_publish_made_for_kids,
        )

    async def list_recent_videos(self, *, limit: int = 20) -> list[VideoPipelineState]:
        statement = (
            select(Video)
            .options(selectinload(Video.asset), selectinload(Video.channel))
            .order_by(Video.created_at.desc(), Video.id.desc())
            .limit(max(1, min(limit, 100)))
        )
        videos = (await self.session.scalars(statement)).all()
        states: list[VideoPipelineState] = []
        for video in videos:
            script_metadata = await self._get_latest_script_metadata(video_id=video.id)
            asset_details = self.asset_service.describe_asset(video.asset)
            states.append(
                self._build_state(
                    video,
                    channel_slug=video.channel.slug if video.channel is not None else None,
                    script_id=script_metadata["script_id"],
                    script_status=script_metadata["script_status"],
                    asset_path=asset_details.source_path if asset_details else None,
                    asset_name=asset_details.name if asset_details else None,
                    asset_slug=asset_details.slug if asset_details else None,
                    asset_type=asset_details.asset_type if asset_details else None,
                    asset_channel_slug=asset_details.channel_slug if asset_details else None,
                    asset_topic=asset_details.topic if asset_details else None,
                    asset_tags=asset_details.tags if asset_details else None,
                    script_text=script_metadata["script_text"],
                    hook=script_metadata["hook"],
                    body_blocks=script_metadata["body_blocks"],
                    call_to_action=script_metadata["call_to_action"],
                    estimated_duration_seconds=script_metadata["estimated_duration_seconds"],
                    style_tone=script_metadata["style_tone"],
                    content_brain_context_used=bool(script_metadata["content_brain_context_used"]),
                    winning_signals_count=int(script_metadata["winning_signals_count"] or 0),
                    weak_signals_count=int(script_metadata["weak_signals_count"] or 0),
                    applied_reason_tags=list(script_metadata["applied_reason_tags"] or []),
                )
            )
        return states

    async def create_local_test_video(
        self,
        *,
        topic: str,
        channel_slug: str,
        channel_name: str,
        video_title: str | None = None,
        execution_mode: VideoExecutionMode = VideoExecutionMode.FAKE,
        style_tone: str | None = None,
        target_duration_seconds: int | None = None,
    ) -> VideoPipelineState:
        preset = await self.get_channel_preset(channel_slug=channel_slug)
        if self.session.in_transaction():
            await self.session.rollback()
        if execution_mode == VideoExecutionMode.REAL:
            return await self._create_real_test_video(
                topic=topic,
                channel_slug=channel_slug,
                channel_name=channel_name,
                video_title=video_title,
                preset=preset,
                style_tone=style_tone,
                target_duration_seconds=target_duration_seconds,
            )
        return await self._create_fake_test_video(
            topic=topic,
            channel_slug=channel_slug,
            channel_name=channel_name,
            video_title=video_title,
            preset=preset,
            style_tone=style_tone,
            target_duration_seconds=target_duration_seconds,
        )

    async def list_channel_presets(self) -> list[ChannelPresetRecord]:
        presets_path = self._channel_presets_dir()
        if not presets_path.exists():
            return []

        records: list[ChannelPresetRecord] = []
        for preset_file in sorted(presets_path.glob("*.json")):
            record = self._read_channel_preset_file(preset_file)
            if record is not None:
                records.append(record)
        records.sort(key=lambda item: item.channel_slug)
        return records

    async def get_channel_preset(self, *, channel_slug: str) -> ChannelPresetRecord | None:
        preset_file = self._channel_preset_path(channel_slug)
        if not preset_file.exists():
            return None
        return self._read_channel_preset_file(preset_file)

    async def upsert_channel_preset(
        self,
        *,
        channel_slug: str,
        channel_name: str,
        default_topic_style: str | None = None,
        default_visual_template: str = "default",
        default_asset_slug: str | None = None,
        default_cta: str | None = None,
        target_duration_seconds: int | None = None,
    ) -> ChannelPresetRecord:
        normalized_slug = self._normalize_channel_slug(channel_slug)
        normalized_name = channel_name.strip()
        if not normalized_name:
            raise ValueError("channel_name is required")
        normalized_template = self._normalize_visual_template(default_visual_template)
        normalized_topic_style = self._normalize_optional_text(default_topic_style)
        normalized_asset_slug = self._normalize_optional_text(default_asset_slug)
        normalized_cta = self._normalize_optional_text(default_cta)
        normalized_duration = self._normalize_optional_duration(target_duration_seconds)

        record = ChannelPresetRecord(
            channel_slug=normalized_slug,
            channel_name=normalized_name,
            default_topic_style=normalized_topic_style,
            default_visual_template=normalized_template,
            default_asset_slug=normalized_asset_slug,
            default_cta=normalized_cta,
            target_duration_seconds=normalized_duration,
        )
        preset_file = self._channel_preset_path(normalized_slug)
        self._write_channel_preset_file(preset_file, record)
        return record

    async def update_script(
        self,
        *,
        video_id: int,
        script_text: str,
        hook: str | None = None,
        body_blocks: list[str] | None = None,
        call_to_action: str | None = None,
        estimated_duration_seconds: int | None = None,
        style_tone: str | None = None,
    ) -> VideoPipelineState:
        statement = (
            select(Video)
            .options(selectinload(Video.asset), selectinload(Video.channel))
            .where(Video.id == video_id)
        )
        video = await self.session.scalar(statement)
        if video is None:
            raise ValueError(f"Video {video_id} not found")
        if video.stage_status != VideoStageStatus.SCRIPT_APPROVED:
            raise ValueError("Script can only be edited before TTS starts")

        script = await self._get_latest_script(video_id=video_id)
        if script is None:
            raise ValueError(f"Script for video {video_id} not found")
        asset_details = self.asset_service.describe_asset(video.asset)

        updated_script = self._normalize_updated_script(
            script_text=script_text,
            hook=hook,
            body_blocks=body_blocks,
            call_to_action=call_to_action,
            estimated_duration_seconds=estimated_duration_seconds,
            style_tone=style_tone,
            existing_script=script,
        )

        script.hook = str(updated_script["hook"] or "")
        script.content = str(updated_script["script"] or "")
        generation_payload = dict(script.generation_payload or {})
        generation_payload["script"] = updated_script
        script.generation_payload = generation_payload
        script.llm_input_hash = None
        script.llm_cache_key = None
        await self.session.flush()

        return self._build_state(
            video,
            channel_slug=video.channel.slug if video.channel is not None else None,
            script_id=script.id,
            script_status=script.status.value,
            asset_path=asset_details.source_path if asset_details else None,
            asset_name=asset_details.name if asset_details else None,
            asset_slug=asset_details.slug if asset_details else None,
            asset_type=asset_details.asset_type if asset_details else None,
            asset_channel_slug=asset_details.channel_slug if asset_details else None,
            asset_topic=asset_details.topic if asset_details else None,
            asset_tags=asset_details.tags if asset_details else None,
            script_text=str(updated_script["script"] or ""),
            hook=str(updated_script["hook"] or ""),
            body_blocks=list(updated_script["body_blocks"] or []),
            call_to_action=str(updated_script["call_to_action"] or ""),
            estimated_duration_seconds=int(updated_script["estimated_duration_seconds"] or 0) or None,
            style_tone=str(updated_script["style_tone"] or ""),
        )

    async def run_tts(self, *, video_id: int, execution_mode: VideoExecutionMode = VideoExecutionMode.FAKE):
        fake_duration_seconds = None
        if execution_mode == VideoExecutionMode.FAKE and self._provided_tts_worker is None:
            fake_duration_seconds = await self._resolve_fake_tts_duration_seconds(video_id=video_id)
        worker = self._build_tts_worker(execution_mode, fake_duration_seconds=fake_duration_seconds)
        return await worker.generate(video_id=video_id)

    async def generate_captions(
        self,
        *,
        video_id: int,
        execution_mode: VideoExecutionMode = VideoExecutionMode.FAKE,
    ):
        return await self.caption_worker.generate(
            video_id=video_id,
            use_whisper=execution_mode == VideoExecutionMode.REAL,
        )

    async def select_asset(
        self,
        *,
        video_id: int,
        asset_id: int | None = None,
        asset_slug: str | None = None,
        channel_slug: str | None = None,
        topic: str | None = None,
        tags: list[str] | None = None,
    ):
        return await self.asset_service.select_local_asset(
            video_id=video_id,
            asset_id=asset_id,
            asset_slug=asset_slug,
            channel_slug=channel_slug,
            topic=topic,
            tags=tags,
        )

    async def list_assets(
        self,
        *,
        channel_slug: str | None = None,
        topic: str | None = None,
        tags: list[str] | None = None,
    ):
        return await self.asset_service.list_assets(channel_slug=channel_slug, topic=topic, tags=tags)

    async def register_local_asset(
        self,
        *,
        relative_path: str,
        name: str | None = None,
        slug: str | None = None,
        asset_type: str | None = None,
        license_name: str = "generated-local",
        license_url: str | None = None,
        channel_slug: str | None = None,
        topic: str | None = None,
        tags: list[str] | None = None,
    ):
        return await self.asset_service.register_local_asset(
            relative_path=relative_path,
            name=name,
            slug=slug,
            asset_type=asset_type,
            license_name=license_name,
            license_url=license_url,
            channel_slug=channel_slug,
            topic=topic,
            tags=tags,
        )

    async def register_uploaded_asset(
        self,
        *,
        file_bytes: bytes,
        original_filename: str | None,
        name: str | None = None,
        slug: str | None = None,
        asset_type: str | None = None,
        license_name: str = "generated-local",
        license_url: str | None = None,
        channel_slug: str | None = None,
        topic: str | None = None,
        tags: list[str] | str | None = None,
    ):
        return await self.asset_service.register_uploaded_asset(
            file_bytes=file_bytes,
            original_filename=original_filename,
            name=name,
            slug=slug,
            asset_type=asset_type,
            license_name=license_name,
            license_url=license_url,
            channel_slug=channel_slug,
            topic=topic,
            tags=tags,
        )

    async def update_video_performance(
        self,
        *,
        video_id: int,
        performance_label: str,
        notes: str | None = None,
        reason_tags: list[str] | None = None,
    ):
        return await self.content_brain_service.update_video_performance(
            video_id=video_id,
            performance_label=performance_label,
            notes=notes,
            reason_tags=reason_tags,
        )

    async def list_content_brain_signals(
        self,
        *,
        channel_slug: str | None = None,
        topic: str | None = None,
    ):
        return await self.content_brain_service.list_signals(channel_slug=channel_slug, topic=topic)

    async def get_content_brain_context(
        self,
        *,
        channel_slug: str | None = None,
        topic: str | None = None,
    ) -> dict[str, object] | None:
        return await self.content_brain_service.build_script_context(channel_slug=channel_slug, topic=topic)

    async def get_video_performance(self, *, video_id: int):
        return await self.content_brain_service.get_video_performance(video_id=video_id)

    async def render_preview(self, *, video_id: int, visual_template: str | None = None):
        return await self.render_worker.render_preview(video_id=video_id, visual_template=visual_template)

    async def regenerate_preview(
        self,
        *,
        video_id: int,
        asset_id: int | None = None,
        visual_template: str | None = None,
    ) -> VideoPipelineState:
        statement = select(Video).options(selectinload(Video.asset), selectinload(Video.channel)).where(Video.id == video_id)
        video = await self.session.scalar(statement)
        if video is None:
            raise ValueError(f"Video {video_id} not found")
        if video.stage_status == VideoStageStatus.FINAL_RENDERED or video.status == WorkflowStatus.COMPLETED:
            raise ValueError("Preview cannot be regenerated after final render")
        if not video.audio_path:
            raise ValueError("Audio is required before regenerating preview")
        if not video.caption_path:
            raise ValueError("Captions are required before regenerating preview")

        if asset_id is not None:
            asset = await self.asset_service._get_asset_by_id(asset_id)
            if asset is None:
                raise ValueError(f"Asset {asset_id} not found")
            self.asset_service._ensure_supported_background_asset(
                Path(asset.source_path) if asset.source_path else None,
                asset.asset_type,
            )
            video.asset_id = asset.id
            video.asset = asset
            await self.session.flush()
        elif video.asset is None or not video.asset.source_path:
            raise ValueError("Video asset is required before regenerating preview")

        video.preview_approved_at = None
        video.stage_status = VideoStageStatus.ASSET_READY
        await self.session.flush()

        await self.render_worker.regenerate_preview(video_id=video_id, visual_template=visual_template)
        return await self.get_status(video_id=video_id)

    async def approve_preview(self, *, video_id: int):
        return await self.render_worker.approve_preview(video_id=video_id)

    async def render_final(self, *, video_id: int):
        return await self.render_worker.render_final(video_id=video_id)

    async def create_export_package(self, *, video_id: int) -> VideoPipelineState:
        statement = (
            select(Video)
            .options(selectinload(Video.asset), selectinload(Video.channel), selectinload(Video.scripts))
            .where(Video.id == video_id)
        )
        video = await self.session.scalar(statement)
        if video is None:
            raise ValueError(f"Video {video_id} not found")
        if video.stage_status != VideoStageStatus.FINAL_RENDERED:
            raise ValueError("Export package is only available after final render")
        if not video.final_path:
            raise ValueError("Final render is required before exporting")
        if not video.caption_path:
            raise ValueError("Captions are required before exporting")

        final_source = self._storage_relative_to_absolute_path(video.final_path)
        if not final_source.exists():
            raise ValueError("Final render file not found")
        caption_source = self._storage_relative_to_absolute_path(video.caption_path)
        if not caption_source.exists():
            raise ValueError("Captions file not found")
        preview_source = self._storage_relative_to_absolute_path(video.preview_path) if video.preview_path else None
        asset_source = self._storage_relative_to_absolute_path(video.asset.source_path) if video.asset and video.asset.source_path else None

        script_metadata = await self._get_latest_script_metadata(video_id=video_id)
        asset_details = self.asset_service.describe_asset(video.asset)
        state = self._build_state(
            video,
            channel_slug=video.channel.slug if video.channel is not None else None,
            script_id=script_metadata["script_id"],
            script_status=script_metadata["script_status"],
            asset_path=asset_details.source_path if asset_details else None,
            asset_name=asset_details.name if asset_details else None,
            asset_slug=asset_details.slug if asset_details else None,
            asset_type=asset_details.asset_type if asset_details else None,
            asset_channel_slug=asset_details.channel_slug if asset_details else None,
            asset_topic=asset_details.topic if asset_details else None,
            asset_tags=asset_details.tags if asset_details else None,
            script_text=script_metadata["script_text"],
            hook=script_metadata["hook"],
            body_blocks=script_metadata["body_blocks"],
            call_to_action=script_metadata["call_to_action"],
            estimated_duration_seconds=script_metadata["estimated_duration_seconds"],
            style_tone=script_metadata["style_tone"],
        )

        export_dir = self._export_package_dir(video.slug)
        export_dir.mkdir(parents=True, exist_ok=True)
        export_final_path = export_dir / "final.mp4"
        shutil.copy2(final_source, export_final_path)

        export_preview_path: Path | None = None
        if preview_source is not None and preview_source.exists():
            export_preview_path = export_dir / "preview.mp4"
            shutil.copy2(preview_source, export_preview_path)

        export_caption_path = export_dir / "captions.srt"
        shutil.copy2(caption_source, export_caption_path)

        export_metadata_path = export_dir / "metadata.json"
        export_metadata = self._build_export_metadata(
            video=video,
            state=state,
            asset_source=asset_source,
            export_dir=export_dir,
            export_final_path=export_final_path,
            export_preview_path=export_preview_path,
            export_caption_path=export_caption_path,
            export_metadata_path=export_metadata_path,
        )
        export_metadata_path.write_text(json.dumps(export_metadata, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        await self.session.flush()
        return await self.get_status(video_id=video_id)

    async def create_youtube_publish_prep(
        self,
        *,
        video_id: int,
        title: str | None = None,
        description: str | None = None,
        tags: list[str] | None = None,
        visibility: str = "private",
        made_for_kids: bool = False,
    ) -> VideoPipelineState:
        statement = (
            select(Video)
            .options(selectinload(Video.asset), selectinload(Video.channel), selectinload(Video.scripts))
            .where(Video.id == video_id)
        )
        video = await self.session.scalar(statement)
        if video is None:
            raise ValueError(f"Video {video_id} not found")
        if video.stage_status != VideoStageStatus.FINAL_RENDERED:
            raise ValueError("YouTube prep is only available after final render")
        if not video.final_path:
            raise ValueError("Final render is required before creating YouTube prep")

        export_state = await self.get_status(video_id=video_id)
        if not export_state.export_metadata_path or not export_state.export_final_path or not export_state.export_caption_path:
            await self.create_export_package(video_id=video_id)
            export_state = await self.get_status(video_id=video_id)

        youtube_publish_path = self._youtube_publish_path(video.slug)
        youtube_publish_payload = self._build_youtube_publish_payload(
            video=video,
            state=export_state,
            title=title,
            description=description,
            tags=tags,
            visibility=visibility,
            made_for_kids=made_for_kids,
        )
        youtube_publish_path.parent.mkdir(parents=True, exist_ok=True)
        youtube_publish_path.write_text(
            json.dumps(youtube_publish_payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        await self.session.flush()
        return await self.get_status(video_id=video_id)

    async def get_publish_readiness(self, *, video_id: int) -> dict[str, object]:
        state = await self.get_status(video_id=video_id)
        if state.stage_status != VideoStageStatus.FINAL_RENDERED.value:
            raise ValueError("Publish readiness is only available after final render")

        def _check_path(path_value: str | None) -> bool:
            if not path_value:
                return False
            try:
                resolved_path = self._storage_relative_to_absolute_path(path_value)
            except ValueError:
                return False
            return resolved_path.exists()

        final_exists = _check_path(state.final_path)
        export_dir_exists = bool(state.export_package_dir and self._storage_relative_to_absolute_path(state.export_package_dir).exists())
        export_metadata_exists = _check_path(state.export_metadata_path)
        captions_exists = _check_path(state.export_caption_path)
        youtube_publish_exists = _check_path(state.youtube_publish_path)
        title_value = self._normalize_optional_text(state.youtube_publish_title)
        description_value = self._normalize_optional_text(state.youtube_publish_description)
        tags_value = [tag for tag in (state.youtube_publish_tags or []) if str(tag).strip()]
        visibility_value = self._normalize_optional_text(state.youtube_publish_visibility)
        made_for_kids_value = state.youtube_publish_made_for_kids
        content_brain_label = self._normalize_optional_text(state.performance_label) or "unknown"

        items = [
            {
                "key": "final_path",
                "label": "final_path existe",
                "ready": final_exists,
                "value": state.final_path,
            },
            {
                "key": "export_package",
                "label": "export package existe",
                "ready": export_dir_exists,
                "value": state.export_package_dir,
            },
            {
                "key": "export_metadata",
                "label": "metadata.json existe",
                "ready": export_metadata_exists,
                "value": state.export_metadata_path,
            },
            {
                "key": "captions",
                "label": "captions.srt existe",
                "ready": captions_exists,
                "value": state.export_caption_path,
            },
            {
                "key": "youtube_publish",
                "label": "youtube_publish.json existe",
                "ready": youtube_publish_exists,
                "value": state.youtube_publish_path,
            },
            {
                "key": "title",
                "label": "title preenchido",
                "ready": bool(title_value),
                "value": title_value,
            },
            {
                "key": "description",
                "label": "description preenchida",
                "ready": bool(description_value),
                "value": description_value,
            },
            {
                "key": "tags",
                "label": "tags nao vazias",
                "ready": bool(tags_value),
                "value": ", ".join(tags_value) if tags_value else None,
            },
            {
                "key": "visibility",
                "label": "visibility definida",
                "ready": bool(visibility_value),
                "value": visibility_value,
            },
            {
                "key": "made_for_kids",
                "label": "made_for_kids definido",
                "ready": made_for_kids_value is not None,
                "value": "true" if made_for_kids_value else "false" if made_for_kids_value is not None else None,
            },
            {
                "key": "content_brain_label",
                "label": "content_brain label definido",
                "ready": bool(content_brain_label),
                "value": content_brain_label,
            },
        ]
        missing_items = [item["key"] for item in items if not item["ready"]]
        return {
            "video_id": state.video_id,
            "video_slug": state.video_slug,
            "channel_slug": state.channel_slug,
            "stage_status": state.stage_status,
            "overall_status": "ready" if not missing_items else "missing_items",
            "ready": not missing_items,
            "missing_items": missing_items,
            "items": items,
        }

    async def get_status(self, *, video_id: int) -> VideoPipelineState:
        statement = select(Video).options(selectinload(Video.asset), selectinload(Video.channel)).where(Video.id == video_id)
        video = await self.session.scalar(statement)
        if video is None:
            raise ValueError(f"Video {video_id} not found")
        script_metadata = await self._get_latest_script_metadata(video_id=video_id)
        asset_details = self.asset_service.describe_asset(video.asset)
        return self._build_state(
            video,
            channel_slug=video.channel.slug if video.channel is not None else None,
            script_id=script_metadata["script_id"],
            script_status=script_metadata["script_status"],
            asset_path=asset_details.source_path if asset_details else None,
            asset_name=asset_details.name if asset_details else None,
            asset_slug=asset_details.slug if asset_details else None,
            asset_type=asset_details.asset_type if asset_details else None,
            asset_channel_slug=asset_details.channel_slug if asset_details else None,
            asset_topic=asset_details.topic if asset_details else None,
            asset_tags=asset_details.tags if asset_details else None,
            script_text=script_metadata["script_text"],
            hook=script_metadata["hook"],
            body_blocks=script_metadata["body_blocks"],
            call_to_action=script_metadata["call_to_action"],
            estimated_duration_seconds=script_metadata["estimated_duration_seconds"],
            style_tone=script_metadata["style_tone"],
        )

    async def _create_fake_test_video(
        self,
        *,
        topic: str,
        channel_slug: str,
        channel_name: str,
        video_title: str | None,
        preset: ChannelPresetRecord | None = None,
        style_tone: str | None = None,
        target_duration_seconds: int | None = None,
    ) -> VideoPipelineState:
        async with self.session.begin():
            channel_name_to_use = preset.channel_name if preset is not None else channel_name
            channel = await self._get_or_create_channel(channel_slug=channel_slug, channel_name=channel_name_to_use)
            video_slug = f"{self._slugify(topic)}-{uuid4().hex[:8]}"
            target_duration = (
                target_duration_seconds
                if target_duration_seconds is not None
                else (preset.target_duration_seconds if preset is not None else None)
            )
            effective_style_tone = style_tone if style_tone is not None else (preset.default_topic_style if preset is not None else None)
            content_brain_context = await self.content_brain_service.build_script_context(
                channel_slug=channel_slug,
                topic=topic,
            )
            video = Video(
                channel_id=channel.id,
                title=video_title or f"Teste local: {topic}",
                slug=video_slug,
                status=WorkflowStatus.APPROVED,
                stage_status=VideoStageStatus.SCRIPT_APPROVED,
                target_duration_seconds=target_duration,
            )
            self.session.add(video)
            await self.session.flush()

            script_content = self._build_fake_script_payload(
                topic=topic,
                style_tone=effective_style_tone,
                default_cta=preset.default_cta if preset is not None else None,
                target_duration_seconds=target_duration,
                content_brain_context=content_brain_context,
            )
            content_brain_context_used = bool(script_content.get("content_brain_context_used"))
            winning_signals_count = int(script_content.get("winning_signals_count") or 0)
            weak_signals_count = int(script_content.get("weak_signals_count") or 0)
            applied_reason_tags = list(script_content.get("applied_reason_tags") or [])
            preset_asset = await self._get_asset_by_slug(preset.default_asset_slug) if preset and preset.default_asset_slug else None
            if preset_asset is not None:
                self.asset_service._ensure_supported_background_asset(
                    Path(preset_asset.source_path) if preset_asset.source_path else None,
                    preset_asset.asset_type,
                )
                video.asset_id = preset_asset.id
                video.asset = preset_asset
                await self.session.flush()
            if preset is not None and preset.default_visual_template:
                self.render_worker.set_visual_template(video_id=video.id, visual_template=preset.default_visual_template)
            else:
                self.render_worker.set_visual_template(video_id=video.id, visual_template="default")
            script = Script(
                video_id=video.id,
                topic=topic,
                version=1,
                status=WorkflowStatus.APPROVED,
                idea=f"Explique {topic} de forma simples.",
                hook=script_content["hook"],
                content=script_content["script"],
                notes="Script local deterministico para fluxo manual.",
                policy_risk_score=Decimal("0.0500"),
                policy_decision="approved",
                generation_payload={
                    "mode": "fake",
                    "topic": topic,
                    "channel_slug": channel_slug,
                    "channel_name": channel_name_to_use,
                    "video_title": video_title,
                    "content_brain_context": content_brain_context,
                    "content_brain": {
                        "context_used": content_brain_context_used,
                        "winning_patterns": (content_brain_context or {}).get("winning_patterns", []) if content_brain_context else [],
                        "weak_patterns": (content_brain_context or {}).get("weak_patterns", []) if content_brain_context else [],
                        "winning_signals_count": winning_signals_count,
                        "weak_signals_count": weak_signals_count,
                        "applied_reason_tags": applied_reason_tags,
                    },
                    "script": script_content,
                },
                llm_model="local-fake",
                llm_cache_key=None,
                llm_input_hash=None,
            )
            self.session.add(script)
            await self.session.flush()

            state = self._build_state(
                video,
                channel_slug=channel_slug,
                script_id=script.id,
                script_status=script.status.value,
                asset_path=preset_asset.source_path if preset_asset is not None else None,
                asset_name=preset_asset.name if preset_asset is not None else None,
                asset_slug=preset_asset.slug if preset_asset is not None else None,
                asset_type=preset_asset.asset_type if preset_asset is not None else None,
                asset_channel_slug=self.asset_service.describe_asset(preset_asset).channel_slug if preset_asset is not None else None,
                asset_topic=self.asset_service.describe_asset(preset_asset).topic if preset_asset is not None else None,
                asset_tags=self.asset_service.describe_asset(preset_asset).tags if preset_asset is not None else None,
                script_text=script_content["script"],
                hook=script_content["hook"],
                body_blocks=script_content["body_blocks"],
                call_to_action=script_content["call_to_action"],
                estimated_duration_seconds=script_content["estimated_duration_seconds"],
                style_tone=script_content["style_tone"],
                visual_template=preset.default_visual_template if preset is not None else None,
                target_duration_seconds=target_duration,
                content_brain_context_used=content_brain_context_used,
                winning_signals_count=winning_signals_count,
                weak_signals_count=weak_signals_count,
                applied_reason_tags=applied_reason_tags,
                export_package_dir=None,
                export_metadata_path=None,
                export_final_path=None,
                export_preview_path=None,
                export_caption_path=None,
            )
        return state

    async def _create_real_test_video(
        self,
        *,
        topic: str,
        channel_slug: str,
        channel_name: str,
        video_title: str | None,
        preset: ChannelPresetRecord | None = None,
        style_tone: str | None = None,
        target_duration_seconds: int | None = None,
    ) -> VideoPipelineState:
        service = ScriptEngineService(session=self.session, settings=self.settings)
        content_brain_context = await self.content_brain_service.build_script_context(
            channel_slug=channel_slug,
            topic=topic,
        )
        effective_style_tone = style_tone if style_tone is not None else (preset.default_topic_style if preset is not None else None)
        effective_target_duration = (
            target_duration_seconds
            if target_duration_seconds is not None
            else (preset.target_duration_seconds if preset is not None else None)
        )
        result = await service.create_test_script(
            topic=topic,
            channel_slug=channel_slug,
            channel_name=preset.channel_name if preset is not None else channel_name,
            video_title=video_title,
            execution_mode=VideoExecutionMode.REAL,
            style_tone=effective_style_tone,
            default_call_to_action=preset.default_cta if preset is not None else None,
            target_duration_seconds=effective_target_duration,
            content_brain_context=content_brain_context,
        )
        statement = select(Video).options(selectinload(Video.channel), selectinload(Video.asset)).where(Video.id == result.video_id)
        video = await self.session.scalar(statement)
        if video is None:
            raise ValueError(f"Video {result.video_id} not found")
        video.target_duration_seconds = effective_target_duration if effective_target_duration is not None else video.target_duration_seconds
        preset_asset = await self._get_asset_by_slug(preset.default_asset_slug) if preset and preset.default_asset_slug else None
        if preset_asset is not None:
            self.asset_service._ensure_supported_background_asset(
                Path(preset_asset.source_path) if preset_asset.source_path else None,
                preset_asset.asset_type,
            )
            video.asset_id = preset_asset.id
            video.asset = preset_asset
        if preset is not None and preset.default_visual_template:
            self.render_worker.set_visual_template(video_id=video.id, visual_template=preset.default_visual_template)
        else:
            self.render_worker.set_visual_template(video_id=video.id, visual_template="default")
        await self.session.flush()
        return self._build_state(
            video,
            channel_slug=video.channel.slug if video.channel is not None else None,
            script_id=result.script_id,
            script_status=result.script_status,
            asset_path=preset_asset.source_path if preset_asset is not None else None,
            asset_name=preset_asset.name if preset_asset is not None else None,
            asset_slug=preset_asset.slug if preset_asset is not None else None,
            asset_type=preset_asset.asset_type if preset_asset is not None else None,
            asset_channel_slug=self.asset_service.describe_asset(preset_asset).channel_slug if preset_asset is not None else None,
            asset_topic=self.asset_service.describe_asset(preset_asset).topic if preset_asset is not None else None,
            asset_tags=self.asset_service.describe_asset(preset_asset).tags if preset_asset is not None else None,
            script_text=result.script_text,
            hook=result.hook,
            body_blocks=result.body_blocks,
            call_to_action=result.call_to_action,
            estimated_duration_seconds=result.estimated_duration_seconds,
            style_tone=result.style_tone,
            visual_template=preset.default_visual_template if preset is not None else None,
            target_duration_seconds=video.target_duration_seconds,
            content_brain_context_used=result.content_brain_context_used,
            winning_signals_count=result.winning_signals_count,
            weak_signals_count=result.weak_signals_count,
            applied_reason_tags=result.applied_reason_tags,
            export_package_dir=None,
            export_metadata_path=None,
            export_final_path=None,
            export_preview_path=None,
            export_caption_path=None,
        )

    async def _get_or_create_channel(self, *, channel_slug: str, channel_name: str) -> Channel:
        statement = select(Channel).where(Channel.slug == channel_slug)
        channel = await self.session.scalar(statement)
        if channel is not None:
            return channel
        channel = Channel(name=channel_name, slug=channel_slug, status=LifecycleStatus.ACTIVE)
        self.session.add(channel)
        await self.session.flush()
        return channel

    def _build_tts_worker(
        self,
        execution_mode: VideoExecutionMode,
        *,
        fake_duration_seconds: float | None = None,
    ) -> TTSWorker:
        if execution_mode == VideoExecutionMode.FAKE and self._provided_tts_worker is not None:
            return self._provided_tts_worker
        if execution_mode == VideoExecutionMode.REAL:
            if not self.settings.openai_api_key:
                raise ValueError("Real execution mode requires OPENAI_API_KEY")
            return TTSWorker(session=self.session, settings=self.settings)
        return TTSWorker(
            session=self.session,
            client=_DeterministicTTSClient(
                self.settings,
                duration_seconds=fake_duration_seconds if fake_duration_seconds is not None else 2.0,
            ),
            settings=self.settings,
            record_cost_log=False,
        )

    async def _resolve_fake_tts_duration_seconds(self, *, video_id: int) -> float:
        state = await self.get_status(video_id=video_id)
        style_tone = str(state.style_tone or "").strip().lower()
        target_duration = state.target_duration_seconds if isinstance(state.target_duration_seconds, int) else None
        estimated_duration = state.estimated_duration_seconds if isinstance(state.estimated_duration_seconds, int) else None
        if style_tone == "viral_micro_short" or (target_duration is not None and target_duration <= 15):
            duration = target_duration or estimated_duration or 10
            return float(max(6, min(duration, 15)))
        if estimated_duration is not None and estimated_duration <= 15:
            return float(max(6, estimated_duration))
        return 2.0

    def _build_state(
        self,
        video: Video,
        *,
        channel_slug: str | None = None,
        script_id: int | None = None,
        script_status: str | None = None,
        asset_path: str | None = None,
        asset_name: str | None = None,
        asset_slug: str | None = None,
        asset_type: str | None = None,
        asset_channel_slug: str | None = None,
        asset_topic: str | None = None,
        asset_tags: list[str] | None = None,
        script_text: str | None = None,
        hook: str | None = None,
        body_blocks: list[str] | None = None,
        call_to_action: str | None = None,
        estimated_duration_seconds: int | None = None,
        style_tone: str | None = None,
        content_brain_context_used: bool = False,
        winning_signals_count: int = 0,
        weak_signals_count: int = 0,
        applied_reason_tags: list[str] | None = None,
        visual_template: str | None = None,
        target_duration_seconds: int | None = None,
        export_package_dir: str | None = None,
        export_metadata_path: str | None = None,
        export_final_path: str | None = None,
        export_preview_path: str | None = None,
        export_caption_path: str | None = None,
    ) -> VideoPipelineState:
        resolved_visual_template = visual_template or self.render_worker.get_visual_template(video.id)
        performance_record = self.content_brain_service.describe_video_performance(video_id=video.id)
        export_paths = self._describe_export_package(video.slug)
        state = VideoPipelineState(
            video_id=video.id,
            video_slug=video.slug,
            channel_slug=channel_slug,
            status=video.status.value,
            stage_status=video.stage_status.value,
            video_title=video.title,
            script_id=script_id,
            script_status=script_status,
            asset_id=video.asset_id,
            audio_path=video.audio_path,
            caption_path=video.caption_path,
            preview_path=video.preview_path,
            final_path=video.final_path,
            asset_path=asset_path,
            asset_name=asset_name,
            asset_slug=asset_slug,
            asset_type=asset_type,
            asset_channel_slug=asset_channel_slug,
            asset_topic=asset_topic,
            asset_tags=asset_tags,
            preview_approved_at=video.preview_approved_at,
            script_text=script_text,
            hook=hook,
            body_blocks=body_blocks,
            call_to_action=call_to_action,
            estimated_duration_seconds=estimated_duration_seconds,
            style_tone=style_tone,
            content_brain_context_used=content_brain_context_used,
            winning_signals_count=winning_signals_count,
            weak_signals_count=weak_signals_count,
            applied_reason_tags=applied_reason_tags,
            visual_template=resolved_visual_template,
            target_duration_seconds=target_duration_seconds if target_duration_seconds is not None else video.target_duration_seconds,
            performance_label=performance_record.performance_label,
            performance_notes=performance_record.notes,
            performance_reason_tags=performance_record.reason_tags,
            export_package_dir=export_package_dir if export_package_dir is not None else export_paths["export_package_dir"],
            export_metadata_path=export_metadata_path if export_metadata_path is not None else export_paths["export_metadata_path"],
            export_final_path=export_final_path if export_final_path is not None else export_paths["export_final_path"],
            export_preview_path=export_preview_path if export_preview_path is not None else export_paths["export_preview_path"],
            export_caption_path=export_caption_path if export_caption_path is not None else export_paths["export_caption_path"],
        )
        youtube_paths = self._describe_youtube_publish_package(video, state)
        state.youtube_publish_path = youtube_paths["youtube_publish_path"]
        state.youtube_publish_title = youtube_paths["youtube_publish_title"]
        state.youtube_publish_description = youtube_paths["youtube_publish_description"]
        state.youtube_publish_tags = youtube_paths["youtube_publish_tags"]
        state.youtube_publish_visibility = youtube_paths["youtube_publish_visibility"]
        state.youtube_publish_made_for_kids = youtube_paths["youtube_publish_made_for_kids"]
        return state

    def _build_production_result_from_state(self, state: VideoPipelineState) -> VideoProductionResult:
        return VideoProductionResult(
            video_id=state.video_id,
            channel_slug=state.channel_slug,
            video_title=state.video_title,
            audio_path=state.audio_path or "",
            caption_path=state.caption_path or "",
            preview_path=state.preview_path or "",
            final_path=state.final_path or "",
            asset_path=state.asset_path or "",
            asset_name=state.asset_name,
            asset_slug=state.asset_slug,
            asset_type=state.asset_type,
            asset_channel_slug=state.asset_channel_slug,
            asset_topic=state.asset_topic,
            asset_tags=state.asset_tags,
            hook=state.hook,
            body_blocks=state.body_blocks,
            call_to_action=state.call_to_action,
            estimated_duration_seconds=state.estimated_duration_seconds,
            style_tone=state.style_tone,
            visual_template=state.visual_template,
            target_duration_seconds=state.target_duration_seconds,
            performance_label=state.performance_label,
            performance_notes=state.performance_notes,
            performance_reason_tags=state.performance_reason_tags,
            content_brain_context_used=state.content_brain_context_used,
            winning_signals_count=state.winning_signals_count,
            weak_signals_count=state.weak_signals_count,
            applied_reason_tags=state.applied_reason_tags,
            export_package_dir=state.export_package_dir,
            export_metadata_path=state.export_metadata_path,
            export_final_path=state.export_final_path,
            export_preview_path=state.export_preview_path,
            export_caption_path=state.export_caption_path,
            youtube_publish_path=state.youtube_publish_path,
            youtube_publish_title=state.youtube_publish_title,
            youtube_publish_description=state.youtube_publish_description,
            youtube_publish_tags=state.youtube_publish_tags,
            youtube_publish_visibility=state.youtube_publish_visibility,
            youtube_publish_made_for_kids=state.youtube_publish_made_for_kids,
        )

    def _build_fake_script(self, *, topic: str) -> str:
        return (
            f"Comece com uma curiosidade simples sobre {topic}. "
            "Depois explique em tres pontos curtos e termine com uma chamada direta para a audiencia."
        )

    def _build_fake_script_payload(
        self,
        *,
        topic: str,
        style_tone: str | None = None,
        default_cta: str | None = None,
        target_duration_seconds: int | None = None,
        content_brain_context: dict[str, object] | None = None,
    ) -> dict[str, object]:
        topic_text = topic.strip() or "o tema"
        viral_mode = _is_viral_micro_short_mode(style_tone, target_duration_seconds)
        winning_patterns = []
        weak_patterns = []
        if isinstance(content_brain_context, dict):
            winning_patterns = [entry for entry in content_brain_context.get("winning_patterns", []) if isinstance(entry, dict)]
            weak_patterns = [entry for entry in content_brain_context.get("weak_patterns", []) if isinstance(entry, dict)]

        def _collect_reason_tags(patterns: list[dict[str, object]]) -> list[str]:
            collected: list[str] = []
            for entry in patterns:
                tags = entry.get("reason_tags")
                if not isinstance(tags, list):
                    continue
                for tag in tags:
                    text = str(tag).strip()
                    if text and text not in collected:
                        collected.append(text)
            return collected

        winning_tags = _collect_reason_tags(winning_patterns)
        weak_tags = _collect_reason_tags(weak_patterns)
        normalized_winning_tags = {
            unicodedata.normalize("NFKD", tag).encode("ascii", "ignore").decode("ascii").lower().strip()
            for tag in winning_tags
        }
        normalized_weak_tags = {
            unicodedata.normalize("NFKD", tag).encode("ascii", "ignore").decode("ascii").lower().strip()
            for tag in weak_tags
        }
        if viral_mode:
            hook = _viral_micro_short_hook(topic_text)
            body_blocks = _viral_micro_short_body_blocks(topic_text)
            call_to_action = ""
            if isinstance(target_duration_seconds, int) and target_duration_seconds > 0:
                estimated_duration_seconds = max(
                    6,
                    min(target_duration_seconds, _VIRAL_MICRO_SHORT_MAX_DURATION_SECONDS),
                )
            else:
                estimated_duration_seconds = _VIRAL_MICRO_SHORT_DEFAULT_DURATION_SECONDS
            style_tone = _VIRAL_MICRO_SHORT_STYLE
        else:
            hook = f"Voce ja viu {topic_text} por este angulo?"
            body_count = 3 + int(hashlib.sha256(topic_text.encode("utf-8")).hexdigest()[:2], 16) % 3
            body_templates = [
                f"Primeiro, simplifique {topic_text} em uma ideia central que a audiencia entenda sem esforco.",
                "Depois, mostre um passo pratico para transformar a explicacao em acao imediata.",
                "Em seguida, destaque o ganho direto para deixar claro por que isso importa agora.",
                f"Se precisar de mais contexto, conecte {topic_text} a um exemplo simples do dia a dia.",
                "Feche reforcando o proximo passo mais facil para a audiencia agir hoje.",
            ]
            if "curiosidade" in normalized_winning_tags:
                hook = f"Voce ja percebeu essa curiosidade sobre {topic_text}?"
            elif winning_tags:
                hook = f"Esse padrao vencedor sobre {topic_text} chama atencao rapido."
            if any(tag in {"generico", "generic"} for tag in normalized_weak_tags):
                body_blocks = [
                    f"Abra com um exemplo concreto de {topic_text} para evitar uma introducao generica.",
                    f"Mostre um caso real que torne {topic_text} facil de imaginar.",
                    "Feche com uma acao objetiva em vez de uma explicacao longa e abstrata.",
                ]
            else:
                body_blocks = body_templates[:body_count]
            if winning_tags:
                body_blocks[-1] = f"Feche reforcando o padrao vencedor de {', '.join(winning_tags[:2])} para manter o ritmo."
            call_to_action = default_cta or (
                "Se isso te ajudou, salva o video e compartilha com alguem que precisa simplificar isso."
            )
            if "cta" in normalized_winning_tags:
                call_to_action = "Se isso fez sentido, salva e manda para quem precisa ver esse atalho."
            estimated_duration_seconds = target_duration_seconds if target_duration_seconds is not None else 24 + len(body_blocks) * 6
        script_text = _build_consolidated_script_text(hook, body_blocks, call_to_action)
        applied_reason_tags = []
        applied_reason_tags.extend(winning_tags[:3])
        for tag in weak_tags:
            if tag not in applied_reason_tags:
                applied_reason_tags.append(tag)
        beats = ["hook", *[f"body_{index + 1}" for index in range(len(body_blocks))]]
        if call_to_action.strip():
            beats.append("cta")
        return {
            "title": f"Roteiro curto: {topic_text}",
            "hook": hook,
            "body_blocks": body_blocks,
            "call_to_action": call_to_action,
            "estimated_duration_seconds": estimated_duration_seconds,
            "style_tone": style_tone or ("viral_micro_short" if viral_mode else "didatico e direto"),
            "script": script_text,
            "beats": beats,
            "content_brain_context_used": bool(winning_patterns or weak_patterns),
            "winning_signals_count": len(winning_patterns),
            "weak_signals_count": len(weak_patterns),
            "applied_reason_tags": applied_reason_tags,
            "content_brain_context": content_brain_context,
        }

    async def _get_latest_script(self, *, video_id: int) -> Script | None:
        statement = select(Script).where(Script.video_id == video_id).order_by(Script.version.desc())
        return await self.session.scalar(statement)

    async def _get_latest_script_metadata(self, *, video_id: int) -> dict[str, int | str | bool | list[str] | None]:
        script = await self._get_latest_script(video_id=video_id)
        if script is None:
            return {
                "script_id": None,
                "script_status": None,
                "script_text": None,
                "hook": None,
                "body_blocks": None,
                "call_to_action": None,
                "estimated_duration_seconds": None,
                "style_tone": None,
                "content_brain_context_used": False,
                "winning_signals_count": 0,
                "weak_signals_count": 0,
                "applied_reason_tags": None,
            }

        generation_payload = script.generation_payload if isinstance(script.generation_payload, dict) else {}
        script_payload = generation_payload.get("script") if isinstance(generation_payload.get("script"), dict) else {}
        script_text = str(script_payload.get("script") or script.content or "").strip() or None
        hook = str(script_payload.get("hook") or script.hook or "").strip() or None
        body_blocks = self._coerce_string_list(script_payload.get("body_blocks"))
        call_to_action = str(script_payload.get("call_to_action") or "").strip() or None
        estimated_duration_seconds = script_payload.get("estimated_duration_seconds")
        if not isinstance(estimated_duration_seconds, int) or estimated_duration_seconds <= 0:
            estimated_duration_seconds = None
        style_tone = str(script_payload.get("style_tone") or "").strip() or None
        if not body_blocks and script_text:
            parsed_script = self._split_script_text(script_text)
            if len(parsed_script) >= 3:
                body_blocks = parsed_script[1:-1]
        if not script_text and body_blocks:
            script_text = self._compose_script_text(
                hook=hook,
                body_blocks=body_blocks,
                call_to_action=call_to_action,
            )
        content_brain_payload = generation_payload.get("content_brain") if isinstance(generation_payload, dict) else None
        content_brain_context_used = bool(content_brain_payload.get("context_used")) if isinstance(content_brain_payload, dict) else False
        winning_signals_count = int(content_brain_payload.get("winning_signals_count") or 0) if isinstance(content_brain_payload, dict) else 0
        weak_signals_count = int(content_brain_payload.get("weak_signals_count") or 0) if isinstance(content_brain_payload, dict) else 0
        applied_reason_tags = self._coerce_string_list(content_brain_payload.get("applied_reason_tags")) if isinstance(content_brain_payload, dict) else []
        return {
            "script_id": script.id,
            "script_status": script.status.value,
            "script_text": script_text,
            "hook": hook,
            "body_blocks": body_blocks or None,
            "call_to_action": call_to_action,
            "estimated_duration_seconds": estimated_duration_seconds,
            "style_tone": style_tone,
            "content_brain_context_used": content_brain_context_used,
            "winning_signals_count": winning_signals_count,
            "weak_signals_count": weak_signals_count,
            "applied_reason_tags": applied_reason_tags,
        }

    def _split_script_text(self, script_text: str) -> list[str]:
        return [part.strip() for part in script_text.split("\n\n") if part.strip()]

    def _compose_script_text(self, *, hook: str | None, body_blocks: list[str] | None, call_to_action: str | None) -> str:
        parts = [part.strip() for part in [hook or "", *(body_blocks or []), call_to_action or ""] if part.strip()]
        return "\n\n".join(parts)

    def _normalize_updated_script(
        self,
        *,
        script_text: str,
        hook: str | None,
        body_blocks: list[str] | None,
        call_to_action: str | None,
        estimated_duration_seconds: int | None,
        style_tone: str | None,
        existing_script: Script,
    ) -> dict[str, object]:
        script_text_value = script_text.strip()
        parsed_blocks = self._split_script_text(script_text_value)
        current_hook = str(existing_script.hook or "").strip() or None
        current_body_blocks: list[str] | None = None
        current_call_to_action: str | None = None
        current_style_tone = None
        current_duration = None

        generation_payload = existing_script.generation_payload if isinstance(existing_script.generation_payload, dict) else {}
        existing_script_payload = generation_payload.get("script") if isinstance(generation_payload.get("script"), dict) else {}
        if isinstance(existing_script_payload, dict):
            current_body_blocks = self._coerce_string_list(existing_script_payload.get("body_blocks")) or None
            current_call_to_action = str(existing_script_payload.get("call_to_action") or "").strip() or None
            current_style_tone = str(existing_script_payload.get("style_tone") or "").strip() or None
            current_duration_raw = existing_script_payload.get("estimated_duration_seconds")
            if isinstance(current_duration_raw, int) and current_duration_raw > 0:
                current_duration = current_duration_raw

        if len(parsed_blocks) >= 3:
            current_hook = parsed_blocks[0]
            current_body_blocks = parsed_blocks[1:-1]
            current_call_to_action = parsed_blocks[-1]
        elif not current_body_blocks:
            current_body_blocks = self._coerce_string_list(existing_script_payload.get("body_blocks")) or None

        if hook is not None:
            current_hook = hook.strip() or None
        if body_blocks is not None:
            current_body_blocks = self._coerce_string_list(body_blocks) or None
        if call_to_action is not None:
            current_call_to_action = call_to_action.strip() or None
        if style_tone is not None:
            current_style_tone = style_tone.strip() or None
        if estimated_duration_seconds is not None and estimated_duration_seconds > 0:
            current_duration = estimated_duration_seconds

        normalized_body_blocks = current_body_blocks or []
        if len(normalized_body_blocks) > 5:
            normalized_body_blocks = normalized_body_blocks[:5]

        normalized_script_text = self._compose_script_text(
            hook=current_hook,
            body_blocks=normalized_body_blocks,
            call_to_action=current_call_to_action,
        )
        if not normalized_script_text:
            normalized_script_text = script_text_value

        if current_duration is None:
            current_duration = max(18, 12 + len(normalized_body_blocks) * 6)
        if current_style_tone is None:
            current_style_tone = "didatico e direto"

        return {
            "title": f"Roteiro curto: {existing_script.topic or existing_script.video_id}",
            "hook": current_hook or "",
            "body_blocks": normalized_body_blocks,
            "call_to_action": current_call_to_action or "",
            "estimated_duration_seconds": current_duration,
            "style_tone": current_style_tone,
            "script": normalized_script_text,
            "beats": ["hook", *[f"body_{index + 1}" for index in range(len(normalized_body_blocks))], "cta"],
        }

    def _coerce_string_list(self, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        items: list[str] = []
        for entry in value:
            text = str(entry).strip()
            if text:
                items.append(text)
        return items

    def _export_package_dir(self, video_slug: str) -> Path:
        return self.settings.local_storage_path / "exports" / video_slug

    def _describe_export_package(self, video_slug: str) -> dict[str, str | None]:
        export_dir = self._export_package_dir(video_slug)
        metadata_path = export_dir / "metadata.json"
        if not metadata_path.exists():
            return {
                "export_package_dir": None,
                "export_metadata_path": None,
                "export_final_path": None,
                "export_preview_path": None,
                "export_caption_path": None,
            }
        final_path = export_dir / "final.mp4"
        preview_path = export_dir / "preview.mp4"
        caption_path = export_dir / "captions.srt"
        return {
            "export_package_dir": self._absolute_to_storage_path(export_dir),
            "export_metadata_path": self._absolute_to_storage_path(metadata_path),
            "export_final_path": self._absolute_to_storage_path(final_path) if final_path.exists() else None,
            "export_preview_path": self._absolute_to_storage_path(preview_path) if preview_path.exists() else None,
            "export_caption_path": self._absolute_to_storage_path(caption_path) if caption_path.exists() else None,
        }

    def _youtube_publish_path(self, video_slug: str) -> Path:
        return self._export_package_dir(video_slug) / "youtube_publish.json"

    def _describe_youtube_publish_package(
        self,
        video: Video,
        state: VideoPipelineState,
    ) -> dict[str, str | list[str] | bool | None]:
        publish_path = self._youtube_publish_path(video.slug)
        publish_path_value = self._absolute_to_storage_path(publish_path)
        if publish_path.exists():
            try:
                payload = json.loads(publish_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                payload = None
            if isinstance(payload, dict):
                return {
                    "youtube_publish_path": publish_path_value,
                    "youtube_publish_title": self._normalize_optional_text(payload.get("title")),
                    "youtube_publish_description": self._normalize_optional_text(payload.get("description")),
                    "youtube_publish_tags": self._coerce_string_list(payload.get("tags")),
                    "youtube_publish_visibility": self._normalize_youtube_visibility(payload.get("visibility")),
                    "youtube_publish_made_for_kids": bool(payload.get("made_for_kids", False)),
                }
            return {
                "youtube_publish_path": publish_path_value,
                "youtube_publish_title": None,
                "youtube_publish_description": None,
                "youtube_publish_tags": None,
                "youtube_publish_visibility": None,
                "youtube_publish_made_for_kids": None,
            }

        if state.stage_status != VideoStageStatus.FINAL_RENDERED.value:
            return {
                "youtube_publish_path": None,
                "youtube_publish_title": None,
                "youtube_publish_description": None,
                "youtube_publish_tags": None,
                "youtube_publish_visibility": None,
                "youtube_publish_made_for_kids": None,
            }

        defaults = self._build_youtube_publish_defaults(video=video, state=state)
        return {
            "youtube_publish_path": None,
            "youtube_publish_title": defaults["title"],
            "youtube_publish_description": defaults["description"],
            "youtube_publish_tags": defaults["tags"],
            "youtube_publish_visibility": defaults["visibility"],
            "youtube_publish_made_for_kids": defaults["made_for_kids"],
        }

    def _build_youtube_publish_payload(
        self,
        *,
        video: Video,
        state: VideoPipelineState,
        title: str | None,
        description: str | None,
        tags: list[str] | None,
        visibility: str,
        made_for_kids: bool,
    ) -> dict[str, object]:
        defaults = self._build_youtube_publish_defaults(video=video, state=state)
        normalized_title = self._normalize_optional_text(title) or str(defaults["title"])
        normalized_description = self._normalize_optional_text(description) or str(defaults["description"])
        normalized_tags = self._coerce_string_list(tags) or list(defaults["tags"])
        normalized_visibility = self._normalize_youtube_visibility(visibility)
        return {
            "video_id": state.video_id,
            "slug": video.slug,
            "channel_slug": state.channel_slug,
            "title": normalized_title,
            "description": normalized_description,
            "tags": normalized_tags,
            "visibility": normalized_visibility,
            "made_for_kids": bool(made_for_kids),
            "final_mp4_path": state.export_final_path or state.final_path,
            "captions_path": state.export_caption_path or state.caption_path,
            "metadata_path": state.export_metadata_path,
        }

    def _build_youtube_publish_defaults(self, *, video: Video, state: VideoPipelineState) -> dict[str, object]:
        title = video.title.strip() if isinstance(video.title, str) and video.title.strip() else video.slug
        description_parts: list[str] = []
        if state.hook:
            description_parts.append(state.hook.strip())
        if state.body_blocks:
            description_parts.extend([block.strip() for block in state.body_blocks if block and block.strip()])
        if state.call_to_action:
            description_parts.append(f"CTA: {state.call_to_action.strip()}")
        if state.style_tone:
            description_parts.append(f"Tom: {state.style_tone.strip()}")
        description_parts.append("#shorts")
        tags: list[str] = []
        for tag in [
            state.channel_slug,
            video.channel.slug if video.channel is not None else None,
            state.asset_slug,
            state.asset_type,
            *list(state.asset_tags or []),
            *list(state.performance_reason_tags or []),
            *list(state.applied_reason_tags or []),
            state.style_tone,
        ]:
            normalized_tag = self._normalize_optional_text(tag)
            if normalized_tag and normalized_tag not in tags:
                tags.append(normalized_tag)
        if not tags:
            tags = ["shorts", "video"]
        return {
            "title": title,
            "description": "\n\n".join(description_parts).strip(),
            "tags": tags,
            "visibility": "private",
            "made_for_kids": False,
        }

    def _build_export_metadata(
        self,
        *,
        video: Video,
        state: VideoPipelineState,
        asset_source: Path | None,
        export_dir: Path,
        export_final_path: Path,
        export_preview_path: Path | None,
        export_caption_path: Path,
        export_metadata_path: Path,
    ) -> dict[str, object]:
        return {
            "video_id": state.video_id,
            "slug": video.slug,
            "title": video.title,
            "video_title": state.video_title,
            "channel_slug": state.channel_slug,
            "script": {
                "script_id": state.script_id,
                "script_status": state.script_status,
                "hook": state.hook,
                "body_blocks": state.body_blocks or [],
                "call_to_action": state.call_to_action,
                "script_text": state.script_text,
                "estimated_duration_seconds": state.estimated_duration_seconds,
                "style_tone": state.style_tone,
            },
            "visual_template": state.visual_template,
            "asset": {
                "asset_id": state.asset_id,
                "name": state.asset_name,
                "slug": state.asset_slug,
                "type": state.asset_type,
                "channel_slug": state.asset_channel_slug,
                "topic": state.asset_topic,
                "tags": state.asset_tags or [],
                "path": state.asset_path,
                "source_path": self._absolute_to_storage_path(asset_source) if asset_source is not None else None,
            },
            "content_brain": {
                "performance_label": state.performance_label,
                "notes": state.performance_notes,
                "reason_tags": state.performance_reason_tags or [],
                "context_used": state.content_brain_context_used,
                "winning_signals_count": state.winning_signals_count,
                "weak_signals_count": state.weak_signals_count,
                "applied_reason_tags": state.applied_reason_tags or [],
            },
            "paths": {
                "audio_path": state.audio_path,
                "caption_path": state.caption_path,
                "preview_path": state.preview_path,
                "final_path": state.final_path,
                "export_dir": self._absolute_to_storage_path(export_dir),
                "export_metadata_path": self._absolute_to_storage_path(export_metadata_path),
                "export_final_path": self._absolute_to_storage_path(export_final_path),
                "export_preview_path": self._absolute_to_storage_path(export_preview_path) if export_preview_path is not None else None,
                "export_caption_path": self._absolute_to_storage_path(export_caption_path),
            },
        }

    def _storage_relative_to_absolute_path(self, stored_path: str) -> Path:
        requested_path = Path(stored_path)
        storage_root = self.settings.local_storage_path.resolve()
        if requested_path.is_absolute():
            resolved_path = requested_path.resolve()
        else:
            storage_base = storage_root.parent
            resolved_path = (storage_base / requested_path).resolve()
        try:
            resolved_path.relative_to(storage_root)
        except ValueError as exc:
            raise ValueError("Path must stay within the configured storage directory") from exc
        return resolved_path

    def _absolute_to_storage_path(self, path: Path) -> str:
        storage_root = self.settings.local_storage_path.resolve()
        resolved_path = path.resolve()
        try:
            relative_path = resolved_path.relative_to(storage_root)
        except ValueError as exc:
            raise ValueError("Path must stay within the configured storage directory") from exc
        return str(Path(storage_root.name) / relative_path)

    def _channel_presets_dir(self) -> Path:
        return self.settings.local_storage_path / "config" / "channel-presets"

    def _channel_preset_path(self, channel_slug: str) -> Path:
        return self._channel_presets_dir() / f"{self._normalize_channel_slug(channel_slug)}.json"

    def _write_channel_preset_file(self, path: Path, preset: ChannelPresetRecord) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "channel_slug": preset.channel_slug,
                    "channel_name": preset.channel_name,
                    "default_topic_style": preset.default_topic_style,
                    "default_visual_template": preset.default_visual_template,
                    "default_asset_slug": preset.default_asset_slug,
                    "default_cta": preset.default_cta,
                    "target_duration_seconds": preset.target_duration_seconds,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )

    def _read_channel_preset_file(self, path: Path) -> ChannelPresetRecord | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        channel_slug = self._normalize_channel_slug(str(payload.get("channel_slug") or path.stem))
        channel_name = str(payload.get("channel_name") or "").strip()
        if not channel_name:
            return None
        try:
            default_visual_template = self._normalize_visual_template(str(payload.get("default_visual_template") or "default"))
        except ValueError:
            return None
        target_duration_seconds = self._normalize_optional_duration(payload.get("target_duration_seconds"))
        return ChannelPresetRecord(
            channel_slug=channel_slug,
            channel_name=channel_name,
            default_topic_style=self._normalize_optional_text(payload.get("default_topic_style")),
            default_visual_template=default_visual_template,
            default_asset_slug=self._normalize_optional_text(payload.get("default_asset_slug")),
            default_cta=self._normalize_optional_text(payload.get("default_cta")),
            target_duration_seconds=target_duration_seconds,
        )

    def _normalize_channel_slug(self, value: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
        if not slug:
            raise ValueError("channel_slug is required")
        return slug

    def _normalize_optional_text(self, value: object | None) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _normalize_optional_duration(self, value: object | None) -> int | None:
        if value is None:
            return None
        try:
            duration = int(value)
        except (TypeError, ValueError):
            raise ValueError("target_duration_seconds must be a positive integer")
        if duration <= 0:
            raise ValueError("target_duration_seconds must be a positive integer")
        return duration

    def _normalize_youtube_visibility(self, value: object | None) -> str:
        visibility = str(value or "private").strip().lower()
        if visibility not in {"private", "unlisted", "public"}:
            raise ValueError("Unknown visibility. Allowed values: private, unlisted, public")
        return visibility

    def _normalize_visual_template(self, value: str) -> str:
        template = value.strip().lower()
        if template not in _CHANNEL_PRESET_ALLOWED_TEMPLATES:
            raise ValueError(
                "Unknown visual template. Allowed values: default, dark_overlay, big_captions, viral_reels"
            )
        return template

    async def _get_asset_by_slug(self, asset_slug: str) -> AssetPool | None:
        statement = select(AssetPool).where(AssetPool.slug == asset_slug)
        return await self.session.scalar(statement)

    def _slugify(self, value: str) -> str:
        import re

        slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
        return slug or "video"

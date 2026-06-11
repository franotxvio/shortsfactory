from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.models.core import Channel, Script, Video
from app.models.enums import LifecycleStatus, VideoExecutionMode, VideoStageStatus, WorkflowStatus
from app.services.asset_pool_service import AssetPoolService
from app.services.caption_worker import CaptionWorker
from app.services.media_utils import build_deterministic_mp3_bytes
from app.services.render_worker import RenderWorker
from app.services.script_engine import ScriptEngineService
from app.services.tts_worker import TTSWorker


@dataclass(slots=True)
class VideoProductionResult:
    video_id: int
    audio_path: str
    caption_path: str
    preview_path: str
    final_path: str
    asset_path: str


@dataclass(slots=True)
class VideoPipelineState:
    video_id: int
    video_slug: str | None
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


class _DeterministicTTSClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._audio_bytes: bytes | None = None

    async def generate_tts_audio(self, *, text: str, model: str, voice: str) -> tuple[bytes, str]:
        if self._audio_bytes is None:
            self._audio_bytes = build_deterministic_mp3_bytes(ffmpeg_path=self._settings.ffmpeg_path)
        return self._audio_bytes, "local-fake-tts"


class VideoProductionService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings | None = None,
        tts_worker: TTSWorker | None = None,
        caption_worker: CaptionWorker | None = None,
        asset_service: AssetPoolService | None = None,
        render_worker: RenderWorker | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self._provided_tts_worker = tts_worker
        self.tts_worker = tts_worker or TTSWorker(session, settings=self.settings)
        self.caption_worker = caption_worker or CaptionWorker(session, settings=self.settings)
        self.asset_service = asset_service or AssetPoolService(session, settings=self.settings)
        self.render_worker = render_worker or RenderWorker(session, settings=self.settings)

    async def produce_full_video(self, *, video_id: int, auto_approve_preview: bool = True) -> VideoProductionResult:
        tts_result = await self.run_tts(video_id=video_id, execution_mode=VideoExecutionMode.FAKE)
        caption_result = await self.generate_captions(video_id=video_id, execution_mode=VideoExecutionMode.FAKE)
        asset_result = await self.select_asset(video_id=video_id)
        preview_result = await self.render_preview(video_id=video_id)
        if auto_approve_preview:
            await self.approve_preview(video_id=video_id)
        final_result = await self.render_final(video_id=video_id)
        return VideoProductionResult(
            video_id=video_id,
            audio_path=tts_result.audio_path,
            caption_path=caption_result.caption_path,
            preview_path=preview_result.output_path,
            final_path=final_result.output_path,
            asset_path=asset_result.asset_path,
        )

    async def create_local_test_video(
        self,
        *,
        topic: str,
        channel_slug: str,
        channel_name: str,
        video_title: str | None = None,
        execution_mode: VideoExecutionMode = VideoExecutionMode.FAKE,
    ) -> VideoPipelineState:
        if execution_mode == VideoExecutionMode.REAL:
            return await self._create_real_test_video(
                topic=topic,
                channel_slug=channel_slug,
                channel_name=channel_name,
                video_title=video_title,
            )
        return await self._create_fake_test_video(
            topic=topic,
            channel_slug=channel_slug,
            channel_name=channel_name,
            video_title=video_title,
        )

    async def run_tts(self, *, video_id: int, execution_mode: VideoExecutionMode = VideoExecutionMode.FAKE):
        worker = self._build_tts_worker(execution_mode)
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

    async def select_asset(self, *, video_id: int):
        return await self.asset_service.select_local_asset(video_id=video_id)

    async def render_preview(self, *, video_id: int):
        return await self.render_worker.render_preview(video_id=video_id)

    async def approve_preview(self, *, video_id: int):
        return await self.render_worker.approve_preview(video_id=video_id)

    async def render_final(self, *, video_id: int):
        return await self.render_worker.render_final(video_id=video_id)

    async def get_status(self, *, video_id: int) -> VideoPipelineState:
        statement = select(Video).options(selectinload(Video.asset)).where(Video.id == video_id)
        video = await self.session.scalar(statement)
        if video is None:
            raise ValueError(f"Video {video_id} not found")
        script_id, script_status = await self._get_latest_script_metadata(video_id=video_id)
        return self._build_state(
            video,
            script_id=script_id,
            script_status=script_status,
            asset_path=video.asset.source_path if video.asset and video.asset.source_path else None,
        )

    async def _create_fake_test_video(
        self,
        *,
        topic: str,
        channel_slug: str,
        channel_name: str,
        video_title: str | None,
    ) -> VideoPipelineState:
        async with self.session.begin():
            channel = await self._get_or_create_channel(channel_slug=channel_slug, channel_name=channel_name)
            video_slug = f"{self._slugify(topic)}-{uuid4().hex[:8]}"
            video = Video(
                channel_id=channel.id,
                title=video_title or f"Teste local: {topic}",
                slug=video_slug,
                status=WorkflowStatus.APPROVED,
                stage_status=VideoStageStatus.SCRIPT_APPROVED,
            )
            self.session.add(video)
            await self.session.flush()

            script_content = self._build_fake_script(topic=topic)
            script = Script(
                video_id=video.id,
                topic=topic,
                version=1,
                status=WorkflowStatus.APPROVED,
                idea=f"Explique {topic} de forma simples.",
                hook=f"Voce ja ouviu isso sobre {topic}?",
                content=script_content,
                notes="Script local deterministico para fluxo manual.",
                policy_risk_score=Decimal("0.0500"),
                policy_decision="approved",
                generation_payload={
                    "mode": "fake",
                    "topic": topic,
                    "channel_slug": channel_slug,
                    "channel_name": channel_name,
                    "video_title": video_title,
                },
                llm_model="local-fake",
                llm_cache_key=None,
                llm_input_hash=None,
            )
            self.session.add(script)
            await self.session.flush()

            state = self._build_state(video, script_id=script.id, script_status=script.status.value, asset_path=None)
        return state

    async def _create_real_test_video(
        self,
        *,
        topic: str,
        channel_slug: str,
        channel_name: str,
        video_title: str | None,
    ) -> VideoPipelineState:
        service = ScriptEngineService(session=self.session, settings=self.settings)
        result = await service.create_test_script(
            topic=topic,
            channel_slug=channel_slug,
            channel_name=channel_name,
            video_title=video_title,
            execution_mode=VideoExecutionMode.REAL,
        )
        video = await self.session.get(Video, result.video_id)
        if video is None:
            raise ValueError(f"Video {result.video_id} not found")
        return self._build_state(video, script_id=result.script_id, script_status=result.script_status, asset_path=None)

    async def _get_or_create_channel(self, *, channel_slug: str, channel_name: str) -> Channel:
        statement = select(Channel).where(Channel.slug == channel_slug)
        channel = await self.session.scalar(statement)
        if channel is not None:
            return channel
        channel = Channel(name=channel_name, slug=channel_slug, status=LifecycleStatus.ACTIVE)
        self.session.add(channel)
        await self.session.flush()
        return channel

    def _build_tts_worker(self, execution_mode: VideoExecutionMode) -> TTSWorker:
        if execution_mode == VideoExecutionMode.FAKE and self._provided_tts_worker is not None:
            return self._provided_tts_worker
        if execution_mode == VideoExecutionMode.REAL:
            if not self.settings.openai_api_key:
                raise ValueError("Real execution mode requires OPENAI_API_KEY")
            return TTSWorker(session=self.session, settings=self.settings)
        return TTSWorker(
            session=self.session,
            client=_DeterministicTTSClient(self.settings),
            settings=self.settings,
            record_cost_log=False,
        )

    def _build_state(
        self,
        video: Video,
        *,
        script_id: int | None = None,
        script_status: str | None = None,
        asset_path: str | None = None,
    ) -> VideoPipelineState:
        return VideoPipelineState(
            video_id=video.id,
            video_slug=video.slug,
            status=video.status.value,
            stage_status=video.stage_status.value,
            script_id=script_id,
            script_status=script_status,
            asset_id=video.asset_id,
            audio_path=video.audio_path,
            caption_path=video.caption_path,
            preview_path=video.preview_path,
            final_path=video.final_path,
            asset_path=asset_path,
            preview_approved_at=video.preview_approved_at,
        )

    def _build_fake_script(self, *, topic: str) -> str:
        return (
            f"Comece com uma curiosidade simples sobre {topic}. "
            "Depois explique em tres pontos curtos e termine com uma chamada direta para a audiencia."
        )

    async def _get_latest_script_metadata(self, *, video_id: int) -> tuple[int | None, str | None]:
        statement = select(Script).where(Script.video_id == video_id).order_by(Script.version.desc())
        script = await self.session.scalar(statement)
        if script is None:
            return None, None
        return script.id, script.status.value

    def _slugify(self, value: str) -> str:
        import re

        slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
        return slug or "video"

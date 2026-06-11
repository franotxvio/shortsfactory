from __future__ import annotations

import hashlib
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
    hook: str | None = None
    body_blocks: list[str] | None = None
    call_to_action: str | None = None
    estimated_duration_seconds: int | None = None
    style_tone: str | None = None


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
    script_text: str | None = None
    hook: str | None = None
    body_blocks: list[str] | None = None
    call_to_action: str | None = None
    estimated_duration_seconds: int | None = None
    style_tone: str | None = None


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

    async def list_recent_videos(self, *, limit: int = 20) -> list[VideoPipelineState]:
        statement = (
            select(Video)
            .options(selectinload(Video.asset))
            .order_by(Video.created_at.desc(), Video.id.desc())
            .limit(max(1, min(limit, 100)))
        )
        videos = (await self.session.scalars(statement)).all()
        states: list[VideoPipelineState] = []
        for video in videos:
            script_metadata = await self._get_latest_script_metadata(video_id=video.id)
            states.append(
                self._build_state(
                    video,
                    script_id=script_metadata["script_id"],
                    script_status=script_metadata["script_status"],
                    asset_path=video.asset.source_path if video.asset and video.asset.source_path else None,
                    script_text=script_metadata["script_text"],
                    hook=script_metadata["hook"],
                    body_blocks=script_metadata["body_blocks"],
                    call_to_action=script_metadata["call_to_action"],
                    estimated_duration_seconds=script_metadata["estimated_duration_seconds"],
                    style_tone=script_metadata["style_tone"],
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
            .options(selectinload(Video.asset))
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
            script_id=script.id,
            script_status=script.status.value,
            asset_path=video.asset.source_path if video.asset and video.asset.source_path else None,
            script_text=str(updated_script["script"] or ""),
            hook=str(updated_script["hook"] or ""),
            body_blocks=list(updated_script["body_blocks"] or []),
            call_to_action=str(updated_script["call_to_action"] or ""),
            estimated_duration_seconds=int(updated_script["estimated_duration_seconds"] or 0) or None,
            style_tone=str(updated_script["style_tone"] or ""),
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
        script_metadata = await self._get_latest_script_metadata(video_id=video_id)
        return self._build_state(
            video,
            script_id=script_metadata["script_id"],
            script_status=script_metadata["script_status"],
            asset_path=video.asset.source_path if video.asset and video.asset.source_path else None,
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

            script_content = self._build_fake_script_payload(topic=topic)
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
                    "channel_name": channel_name,
                    "video_title": video_title,
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
                script_id=script.id,
                script_status=script.status.value,
                asset_path=None,
                script_text=script_content["script"],
                hook=script_content["hook"],
                body_blocks=script_content["body_blocks"],
                call_to_action=script_content["call_to_action"],
                estimated_duration_seconds=script_content["estimated_duration_seconds"],
                style_tone=script_content["style_tone"],
            )
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
        return self._build_state(
            video,
            script_id=result.script_id,
            script_status=result.script_status,
            asset_path=None,
            script_text=result.script_text,
            hook=result.hook,
            body_blocks=result.body_blocks,
            call_to_action=result.call_to_action,
            estimated_duration_seconds=result.estimated_duration_seconds,
            style_tone=result.style_tone,
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
        script_text: str | None = None,
        hook: str | None = None,
        body_blocks: list[str] | None = None,
        call_to_action: str | None = None,
        estimated_duration_seconds: int | None = None,
        style_tone: str | None = None,
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
            script_text=script_text,
            hook=hook,
            body_blocks=body_blocks,
            call_to_action=call_to_action,
            estimated_duration_seconds=estimated_duration_seconds,
            style_tone=style_tone,
        )

    def _build_production_result_from_state(self, state: VideoPipelineState) -> VideoProductionResult:
        return VideoProductionResult(
            video_id=state.video_id,
            audio_path=state.audio_path or "",
            caption_path=state.caption_path or "",
            preview_path=state.preview_path or "",
            final_path=state.final_path or "",
            asset_path=state.asset_path or "",
            hook=state.hook,
            body_blocks=state.body_blocks,
            call_to_action=state.call_to_action,
            estimated_duration_seconds=state.estimated_duration_seconds,
            style_tone=state.style_tone,
        )

    def _build_fake_script(self, *, topic: str) -> str:
        return (
            f"Comece com uma curiosidade simples sobre {topic}. "
            "Depois explique em tres pontos curtos e termine com uma chamada direta para a audiencia."
        )

    def _build_fake_script_payload(self, *, topic: str) -> dict[str, object]:
        topic_text = topic.strip() or "o tema"
        hook = f"Voce ja viu {topic_text} por este angulo?"
        body_count = 3 + int(hashlib.sha256(topic_text.encode("utf-8")).hexdigest()[:2], 16) % 3
        body_templates = [
            f"Primeiro, simplifique {topic_text} em uma ideia central que a audiencia entenda sem esforco.",
            "Depois, mostre um passo pratico para transformar a explicacao em acao imediata.",
            "Em seguida, destaque o ganho direto para deixar claro por que isso importa agora.",
            f"Se precisar de mais contexto, conecte {topic_text} a um exemplo simples do dia a dia.",
            "Feche reforcando o proximo passo mais facil para a audiencia agir hoje.",
        ]
        body_blocks = body_templates[:body_count]
        call_to_action = "Se isso te ajudou, salva o video e compartilha com alguem que precisa simplificar isso."
        estimated_duration_seconds = 24 + len(body_blocks) * 6
        script_text = "\n\n".join([hook, *body_blocks, call_to_action])
        return {
            "title": f"Roteiro curto: {topic_text}",
            "hook": hook,
            "body_blocks": body_blocks,
            "call_to_action": call_to_action,
            "estimated_duration_seconds": estimated_duration_seconds,
            "style_tone": "didatico e direto",
            "script": script_text,
            "beats": ["hook", "body_1", "body_2", "body_3", "cta"],
        }

    async def _get_latest_script(self, *, video_id: int) -> Script | None:
        statement = select(Script).where(Script.video_id == video_id).order_by(Script.version.desc())
        return await self.session.scalar(statement)

    async def _get_latest_script_metadata(self, *, video_id: int) -> dict[str, int | str | list[str] | None]:
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
        return {
            "script_id": script.id,
            "script_status": script.status.value,
            "script_text": script_text,
            "hook": hook,
            "body_blocks": body_blocks or None,
            "call_to_action": call_to_action,
            "estimated_duration_seconds": estimated_duration_seconds,
            "style_tone": style_tone,
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

    def _slugify(self, value: str) -> str:
        import re

        slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
        return slug or "video"

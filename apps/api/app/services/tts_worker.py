from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.models.core import CostLog, Script, Video
from app.models.enums import VideoStageStatus, WorkflowStatus
from app.services.media_utils import ensure_parent_dir
from app.services.openai_client import OpenAIJSONClient


@dataclass(slots=True)
class TTSResult:
    video_id: int
    audio_path: str
    cost_usd: Decimal


class TTSWorker:
    def __init__(
        self,
        session: AsyncSession,
        client: OpenAIJSONClient | None = None,
        settings: Settings | None = None,
        record_cost_log: bool = True,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.client = client
        self.record_cost_log = record_cost_log

    async def generate(self, *, video_id: int) -> TTSResult:
        video = await self.session.get(Video, video_id)
        if video is None:
            raise ValueError(f"Video {video_id} not found")
        if video.stage_status != VideoStageStatus.SCRIPT_APPROVED:
            raise ValueError("TTS is only allowed after script approval")

        script = await self._get_approved_script(video_id)
        audio_path = self.settings.audio_output_path / f"{video.slug}.mp3"
        ensure_parent_dir(audio_path)

        client = self._get_client()
        audio_bytes, request_id = await client.generate_tts_audio(
            text=script.content,
            model=self.settings.openai_tts_model,
            voice=self.settings.openai_tts_voice,
        )
        audio_path.write_bytes(audio_bytes)

        cost_usd = _estimate_tts_cost(script.content, self.settings)
        if self.record_cost_log:
            self.session.add(
                CostLog(
                    video_id=video.id,
                    provider="openai",
                    operation="tts",
                    request_id=request_id,
                    model=self.settings.openai_tts_model,
                    cost_usd=cost_usd,
                )
            )
        video.audio_path = str(audio_path)
        video.stage_status = VideoStageStatus.TTS_DONE
        await self.session.flush()

        return TTSResult(video_id=video.id, audio_path=str(audio_path), cost_usd=cost_usd)

    def _get_client(self) -> OpenAIJSONClient:
        if self.client is not None:
            return self.client
        if not self.settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required for real TTS execution")
        self.client = OpenAIJSONClient(self.settings)
        return self.client

    async def _get_approved_script(self, video_id: int) -> Script:
        statement = (
            select(Script)
            .where(Script.video_id == video_id, Script.status == WorkflowStatus.APPROVED)
            .order_by(Script.version.desc())
        )
        script = await self.session.scalar(statement)
        if script is None:
            raise ValueError("Approved script is required before TTS")
        return script


def _estimate_tts_cost(text: str, settings: Settings) -> Decimal:
    characters = len(text)
    cost = (characters / 1_000_000) * settings.openai_tts_cost_per_1m_chars_usd
    return Decimal(str(round(cost, 6)))

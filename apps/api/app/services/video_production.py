from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.services.asset_pool_service import AssetPoolService
from app.services.caption_worker import CaptionWorker
from app.services.render_worker import RenderWorker
from app.services.tts_worker import TTSWorker


@dataclass(slots=True)
class VideoProductionResult:
    video_id: int
    audio_path: str
    caption_path: str
    preview_path: str
    final_path: str
    asset_path: str


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
        self.tts_worker = tts_worker or TTSWorker(session, settings=self.settings)
        self.caption_worker = caption_worker or CaptionWorker(session, settings=self.settings)
        self.asset_service = asset_service or AssetPoolService(session, settings=self.settings)
        self.render_worker = render_worker or RenderWorker(session, settings=self.settings)

    async def produce_full_video(self, *, video_id: int, auto_approve_preview: bool = True) -> VideoProductionResult:
        tts_result = await self.tts_worker.generate(video_id=video_id)
        caption_result = await self.caption_worker.generate(video_id=video_id)
        asset_result = await self.asset_service.select_local_asset(video_id=video_id)
        preview_result = await self.render_worker.render_preview(video_id=video_id)
        if auto_approve_preview:
            await self.render_worker.approve_preview(video_id=video_id)
        final_result = await self.render_worker.render_final(video_id=video_id)
        return VideoProductionResult(
            video_id=video_id,
            audio_path=tts_result.audio_path,
            caption_path=caption_result.caption_path,
            preview_path=preview_result.output_path,
            final_path=final_result.output_path,
            asset_path=asset_result.asset_path,
        )


from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any
from uuid import uuid4

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings, get_settings
from app.models.enums import VideoExecutionMode
from app.services.video_production import VideoProductionService

_JOB_QUEUE_PREFIX = "shortsfactory:video_jobs"
_FULL_PIPELINE_JOB_TYPE = "full_pipeline_fake"
_STEP_JOB_TYPES = {"tts", "captions", "asset", "preview", "approve-preview", "final"}
_TERMINAL_STATUSES = {"succeeded", "failed"}


@dataclass(slots=True)
class VideoJobRecord:
    job_id: str
    video_id: int
    job_type: str
    status: str
    error_message: str | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    visual_template: str | None = None


class VideoJobQueueService:
    def __init__(self, settings: Settings | None = None, redis_client: Redis | None = None) -> None:
        self.settings = settings or get_settings()
        self.redis = redis_client or Redis.from_url(self.settings.redis_url, decode_responses=True)

    async def enqueue_full_pipeline_fake(
        self,
        *,
        video_id: int,
        visual_template: str = "default",
    ) -> VideoJobRecord:
        return await self._enqueue_job(
            video_id=video_id,
            job_type=_FULL_PIPELINE_JOB_TYPE,
            visual_template=visual_template,
        )

    async def enqueue_step(
        self,
        *,
        video_id: int,
        job_type: str,
        visual_template: str = "default",
    ) -> VideoJobRecord:
        normalized_job_type = job_type.strip().lower()
        if normalized_job_type not in _STEP_JOB_TYPES:
            raise ValueError("Unknown job type")
        return await self._enqueue_job(
            video_id=video_id,
            job_type=normalized_job_type,
            visual_template=visual_template,
        )

    async def get_job(self, job_id: str) -> VideoJobRecord | None:
        payload = await self.redis.hgetall(self._job_key(job_id))
        if not payload:
            return None
        return self._record_from_mapping(payload)

    async def get_latest_job_for_video(self, *, video_id: int) -> VideoJobRecord | None:
        job_id = await self.redis.get(self._latest_key(video_id))
        if not job_id:
            return None
        return await self.get_job(str(job_id))

    async def run_job_now(self, job_id: str) -> VideoJobRecord:
        record = await self.get_job(job_id)
        if record is None:
            raise ValueError(f"Job {job_id} not found")
        if record.status in _TERMINAL_STATUSES:
            return record

        started_at = datetime.now(timezone.utc)
        await self._persist_job(
            record,
            status="running",
            started_at=started_at,
            error_message=None,
        )
        try:
            await self._execute_job(record)
        except Exception as error:
            finished_at = datetime.now(timezone.utc)
            await self._persist_job(
                record,
                status="failed",
                started_at=started_at,
                finished_at=finished_at,
                error_message=str(error),
            )
            raise

        finished_at = datetime.now(timezone.utc)
        await self._persist_job(
            record,
            status="succeeded",
            started_at=started_at,
            finished_at=finished_at,
            error_message=None,
        )
        latest = await self.get_job(job_id)
        if latest is None:
            return record
        return latest

    async def run_forever(self) -> None:
        try:
            while True:
                item = await self.redis.blpop(self._queue_key(), timeout=1)
                if item is None:
                    await asyncio.sleep(0.1)
                    continue
                _, job_id = item
                try:
                    await self.run_job_now(str(job_id))
                except Exception:
                    continue
        except asyncio.CancelledError:
            raise

    async def _enqueue_job(self, *, video_id: int, job_type: str, visual_template: str) -> VideoJobRecord:
        job_id = uuid4().hex
        record = VideoJobRecord(
            job_id=job_id,
            video_id=video_id,
            job_type=job_type,
            status="queued",
            created_at=datetime.now(timezone.utc),
            visual_template=visual_template.strip().lower() or "default",
        )
        await self._persist_job(record)
        await self.redis.set(self._latest_key(video_id), job_id)
        await self.redis.lpush(self._queue_key(), job_id)
        return record

    async def _execute_job(self, record: VideoJobRecord) -> None:
        engine = create_async_engine(self.settings.database_url, pool_pre_ping=True)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                service = VideoProductionService(session=session, settings=self.settings)
                try:
                    if record.job_type == _FULL_PIPELINE_JOB_TYPE:
                        await service.produce_full_video(
                            video_id=record.video_id,
                            auto_approve_preview=True,
                            visual_template=record.visual_template or "default",
                        )
                    elif record.job_type == "tts":
                        await service.run_tts(video_id=record.video_id, execution_mode=VideoExecutionMode.FAKE)
                    elif record.job_type == "captions":
                        await service.generate_captions(video_id=record.video_id, execution_mode=VideoExecutionMode.FAKE)
                    elif record.job_type == "asset":
                        await service.select_asset(video_id=record.video_id)
                    elif record.job_type == "preview":
                        await service.render_preview(
                            video_id=record.video_id,
                            visual_template=record.visual_template or "default",
                        )
                    elif record.job_type == "approve-preview":
                        await service.approve_preview(video_id=record.video_id)
                    elif record.job_type == "final":
                        await service.render_final(video_id=record.video_id)
                    else:
                        raise ValueError("Unknown job type")
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise
        finally:
            await engine.dispose()

    async def _persist_job(
        self,
        record: VideoJobRecord,
        *,
        status: str | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        error_message: str | None = None,
    ) -> None:
        next_record = VideoJobRecord(
            job_id=record.job_id,
            video_id=record.video_id,
            job_type=record.job_type,
            status=status or record.status,
            error_message=error_message if error_message is not None else record.error_message,
            created_at=record.created_at,
            started_at=started_at if started_at is not None else record.started_at,
            finished_at=finished_at if finished_at is not None else record.finished_at,
            visual_template=record.visual_template,
        )
        await self.redis.hset(self._job_key(record.job_id), mapping=self._serialize_record(next_record))

    def _serialize_record(self, record: VideoJobRecord) -> dict[str, str]:
        return {
            "job_id": record.job_id,
            "video_id": str(record.video_id),
            "job_type": record.job_type,
            "status": record.status,
            "error_message": record.error_message or "",
            "created_at": record.created_at.isoformat() if record.created_at is not None else "",
            "started_at": record.started_at.isoformat() if record.started_at is not None else "",
            "finished_at": record.finished_at.isoformat() if record.finished_at is not None else "",
            "visual_template": record.visual_template or "",
        }

    def _record_from_mapping(self, payload: dict[str, Any]) -> VideoJobRecord:
        return VideoJobRecord(
            job_id=str(payload.get("job_id") or ""),
            video_id=int(payload.get("video_id") or 0),
            job_type=str(payload.get("job_type") or ""),
            status=str(payload.get("status") or ""),
            error_message=self._normalize_optional_text(payload.get("error_message")),
            created_at=self._parse_datetime(payload.get("created_at")),
            started_at=self._parse_datetime(payload.get("started_at")),
            finished_at=self._parse_datetime(payload.get("finished_at")),
            visual_template=self._normalize_optional_text(payload.get("visual_template")),
        )

    def _parse_datetime(self, value: Any) -> datetime | None:
        text = self._normalize_optional_text(value)
        if not text:
            return None
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            return None

    def _normalize_optional_text(self, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _job_key(self, job_id: str) -> str:
        return f"{_JOB_QUEUE_PREFIX}:job:{job_id}"

    def _latest_key(self, video_id: int) -> str:
        return f"{_JOB_QUEUE_PREFIX}:latest:{video_id}"

    def _queue_key(self) -> str:
        return f"{_JOB_QUEUE_PREFIX}:queue"


@lru_cache(maxsize=1)
def get_video_job_queue_service() -> VideoJobQueueService:
    return VideoJobQueueService()

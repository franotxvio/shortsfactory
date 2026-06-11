from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import Settings, get_settings
from app.models.core import Script, Video

_PERFORMANCE_LABELS = {"unknown", "weak", "average", "winning"}
_CONTENT_BRAIN_STORE = "video_signals.json"


@dataclass(slots=True)
class ContentBrainSignalRecord:
    video_id: int
    video_slug: str | None
    channel_slug: str | None
    topic: str | None
    performance_label: str
    notes: str | None
    reason_tags: list[str] | None
    updated_at: datetime | None = None


class ContentBrainService:
    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()

    async def update_video_performance(
        self,
        *,
        video_id: int,
        performance_label: str,
        notes: str | None = None,
        reason_tags: list[str] | None = None,
    ) -> ContentBrainSignalRecord:
        video = await self._get_video(video_id)
        if video is None:
            raise ValueError(f"Video {video_id} not found")

        normalized_label = self._normalize_label(performance_label)
        normalized_notes = self._normalize_optional_text(notes)
        normalized_reason_tags = self._normalize_tags(reason_tags)
        topic = await self._resolve_video_topic(video_id)
        record = self._build_record(
            video_id=video.id,
            video_slug=video.slug,
            channel_slug=video.channel.slug if video.channel is not None else None,
            topic=topic,
            performance_label=normalized_label,
            notes=normalized_notes,
            reason_tags=normalized_reason_tags,
            updated_at=datetime.now(timezone.utc),
        )
        store = self._read_store()
        store[str(video_id)] = self._record_to_payload(record)
        self._write_store(store)
        return record

    async def get_video_performance(self, *, video_id: int) -> ContentBrainSignalRecord:
        video = await self._get_video(video_id)
        if video is None:
            raise ValueError(f"Video {video_id} not found")
        store = self._read_store()
        payload = store.get(str(video_id))
        return self._build_record_from_video(video, payload)

    def describe_video_performance(self, *, video_id: int) -> ContentBrainSignalRecord:
        store = self._read_store()
        payload = store.get(str(video_id))
        video_id_value = int(payload.get("video_id", video_id)) if isinstance(payload, dict) else video_id
        try:
            return self._build_record_from_payload(video_id=video_id_value, payload=payload)
        except ValueError:
            return self._build_record(
                video_id=video_id,
                video_slug=None,
                channel_slug=None,
                topic=None,
                performance_label="unknown",
                notes=None,
                reason_tags=None,
                updated_at=None,
            )

    async def list_signals(
        self,
        *,
        channel_slug: str | None = None,
        topic: str | None = None,
    ) -> list[ContentBrainSignalRecord]:
        store = self._read_store()
        if not store:
            return []

        statement = (
            select(Video)
            .options(selectinload(Video.channel), selectinload(Video.scripts))
            .order_by(Video.created_at.desc(), Video.id.desc())
        )
        videos = (await self.session.scalars(statement)).all()
        signals: list[ContentBrainSignalRecord] = []
        for video in videos:
            payload = store.get(str(video.id))
            if payload is None:
                continue
            try:
                record = self._build_record_from_video(video, payload)
            except ValueError:
                continue
            if record.performance_label == "unknown":
                continue
            if channel_slug and (record.channel_slug or "").lower() != channel_slug.strip().lower():
                continue
            if topic and not self._topic_matches(record.topic, topic):
                continue
            signals.append(record)
        return signals

    async def build_script_context(
        self,
        *,
        channel_slug: str | None = None,
        topic: str | None = None,
        limit: int = 3,
    ) -> dict[str, object] | None:
        signals = await self.list_signals(channel_slug=channel_slug, topic=topic)
        if not signals:
            return None

        winning_examples = [self._record_summary(record) for record in signals if record.performance_label == "winning"][:limit]
        weak_examples = [self._record_summary(record) for record in signals if record.performance_label == "weak"][:limit]
        if not winning_examples and not weak_examples:
            return None

        return {
            "channel_slug": channel_slug,
            "topic": topic,
            "winning_examples": winning_examples,
            "weak_examples": weak_examples,
            "winning_count": sum(1 for record in signals if record.performance_label == "winning"),
            "weak_count": sum(1 for record in signals if record.performance_label == "weak"),
        }

    def _build_record(
        self,
        *,
        video_id: int,
        video_slug: str | None,
        channel_slug: str | None,
        topic: str | None,
        performance_label: str,
        notes: str | None,
        reason_tags: list[str] | None,
        updated_at: datetime | None,
    ) -> ContentBrainSignalRecord:
        return ContentBrainSignalRecord(
            video_id=video_id,
            video_slug=video_slug,
            channel_slug=channel_slug,
            topic=topic,
            performance_label=performance_label,
            notes=notes,
            reason_tags=reason_tags,
            updated_at=updated_at,
        )

    def _build_record_from_video(self, video: Video, payload: dict[str, object] | None) -> ContentBrainSignalRecord:
        payload = payload or {}
        return self._build_record_from_payload(video_id=video.id, payload=payload, video=video)

    def _build_record_from_payload(
        self,
        *,
        video_id: int,
        payload: dict[str, object] | None,
        video: Video | None = None,
    ) -> ContentBrainSignalRecord:
        payload = payload or {}
        channel_slug = self._normalize_optional_text(payload.get("channel_slug"))
        if channel_slug is None and video is not None and video.channel is not None:
            channel_slug = video.channel.slug
        topic = self._normalize_optional_text(payload.get("topic"))
        if topic is None and video is not None:
            topic = self._resolve_script_topic(video)
        performance_label = self._normalize_label(str(payload.get("performance_label") or "unknown"))
        return self._build_record(
            video_id=video_id,
            video_slug=self._normalize_optional_text(payload.get("video_slug")) or (video.slug if video is not None else None),
            channel_slug=channel_slug,
            topic=topic,
            performance_label=performance_label,
            notes=self._normalize_optional_text(payload.get("notes")),
            reason_tags=self._normalize_tags(payload.get("reason_tags")),
            updated_at=self._parse_datetime(payload.get("updated_at")),
        )

    async def _get_video(self, video_id: int) -> Video | None:
        statement = (
            select(Video)
            .options(selectinload(Video.channel), selectinload(Video.scripts))
            .where(Video.id == video_id)
        )
        return await self.session.scalar(statement)

    async def _resolve_video_topic(self, video_id: int) -> str | None:
        statement = select(Script.topic).where(Script.video_id == video_id).order_by(Script.version.desc())
        topic = await self.session.scalar(statement)
        return self._normalize_optional_text(topic)

    def _resolve_script_topic(self, video: Video) -> str | None:
        if not video.scripts:
            return None
        latest_script = max(video.scripts, key=lambda script: script.version)
        return self._normalize_optional_text(latest_script.topic)

    def _read_store(self) -> dict[str, dict[str, object]]:
        path = self._store_path()
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        store: dict[str, dict[str, object]] = {}
        for key, value in payload.items():
            if isinstance(key, str) and isinstance(value, dict):
                store[key] = value
        return store

    def _write_store(self, store: dict[str, dict[str, object]]) -> None:
        path = self._store_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(store, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    def _store_path(self) -> Path:
        return self.settings.local_storage_path / "config" / "contentbrain" / _CONTENT_BRAIN_STORE

    def _record_to_payload(self, record: ContentBrainSignalRecord) -> dict[str, object]:
        return {
            "video_id": record.video_id,
            "video_slug": record.video_slug,
            "channel_slug": record.channel_slug,
            "topic": record.topic,
            "performance_label": record.performance_label,
            "notes": record.notes,
            "reason_tags": record.reason_tags or [],
            "updated_at": record.updated_at.isoformat() if record.updated_at is not None else None,
        }

    def _topic_matches(self, record_topic: str | None, requested_topic: str) -> bool:
        normalized_record_topic = (record_topic or "").strip().lower()
        normalized_requested_topic = requested_topic.strip().lower()
        if not normalized_requested_topic:
            return True
        if not normalized_record_topic:
            return False
        return (
            normalized_requested_topic == normalized_record_topic
            or normalized_requested_topic in normalized_record_topic
            or normalized_record_topic in normalized_requested_topic
        )

    def _normalize_label(self, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in _PERFORMANCE_LABELS:
            raise ValueError("performance_label must be one of: unknown, weak, average, winning")
        return normalized

    def _normalize_optional_text(self, value: object | None) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _normalize_tags(self, value: object | None) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            items = [part.strip() for part in value.split(",")]
            return [item for item in items if item]
        if not isinstance(value, list):
            return []
        items: list[str] = []
        for entry in value:
            text = str(entry).strip()
            if text:
                items.append(text)
        return items

    def _parse_datetime(self, value: object | None) -> datetime | None:
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    def _record_summary(self, record: ContentBrainSignalRecord) -> dict[str, object]:
        return {
            "video_id": record.video_id,
            "video_slug": record.video_slug,
            "channel_slug": record.channel_slug,
            "topic": record.topic,
            "performance_label": record.performance_label,
            "notes": record.notes,
            "reason_tags": record.reason_tags or [],
        }

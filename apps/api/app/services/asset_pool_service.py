from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.models.core import AssetPool, Video
from app.models.enums import LifecycleStatus, VideoStageStatus
from app.services.media_utils import ensure_parent_dir, run_command

_ALLOWED_ASSET_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
_DEFAULT_ASSET_SLUG = "system-default-background"
_DEFAULT_ASSET_NAME = "Default Background"
_ASSET_MANIFEST_FILENAME = ".asset-pool-manifest.json"
_PREVIEW_LOCKED_STAGES = {
    VideoStageStatus.PREVIEW_READY,
    VideoStageStatus.PREVIEW_APPROVED,
    VideoStageStatus.FINAL_RENDERED,
}


@dataclass(slots=True)
class AssetSelectionResult:
    video_id: int
    asset_id: int
    asset_path: str
    asset_name: str | None = None
    asset_slug: str | None = None
    asset_type: str | None = None
    channel_slug: str | None = None
    topic: str | None = None
    tags: list[str] | None = None


@dataclass(slots=True)
class AssetPoolRecord:
    asset_id: int
    asset_type: str
    name: str
    slug: str
    source_path: str | None
    license_name: str
    license_url: str | None
    status: str
    channel_slug: str | None = None
    topic: str | None = None
    tags: list[str] | None = None
    is_default: bool = False


class AssetPoolService:
    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()

    async def list_assets(
        self,
        *,
        channel_slug: str | None = None,
        topic: str | None = None,
        tags: list[str] | None = None,
        include_inactive: bool = False,
    ) -> list[AssetPoolRecord]:
        await self._get_or_create_default_asset()
        statement = select(AssetPool).order_by(AssetPool.id.desc())
        if not include_inactive:
            statement = statement.where(AssetPool.status == LifecycleStatus.ACTIVE)
        assets = (await self.session.scalars(statement)).all()
        records = [self._describe_asset(asset) for asset in assets]
        filtered_records = [
            record
            for record in records
            if self._matches_filters(record, channel_slug=channel_slug, topic=topic, tags=tags)
        ]
        filtered_records.sort(key=lambda record: (not record.is_default, -record.asset_id))
        return filtered_records

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
    ) -> AssetPoolRecord:
        resolved_path = self._resolve_asset_path(relative_path)
        storage_path = self._storage_relative_path(resolved_path)
        normalized_slug = self._normalize_slug(slug or resolved_path.stem)
        normalized_name = (name or resolved_path.stem.replace("-", " ").replace("_", " ").title()).strip()
        normalized_tags = self._normalize_tags(tags)
        normalized_asset_type = self._normalize_asset_type(asset_type, resolved_path)
        self._ensure_supported_background_asset(resolved_path, normalized_asset_type)
        storage_path = str(resolved_path.resolve())

        statement = select(AssetPool).where(AssetPool.source_path == storage_path)
        asset = await self.session.scalar(statement)
        existing_by_slug = await self.session.scalar(select(AssetPool).where(AssetPool.slug == normalized_slug))
        if existing_by_slug is not None and existing_by_slug.source_path != storage_path and (
            asset is None or existing_by_slug.id != asset.id
        ):
            raise ValueError(f"Asset slug {normalized_slug} is already registered for another file")
        if asset is None:
            asset = existing_by_slug

        if asset is None:
            asset = AssetPool(
                asset_type=normalized_asset_type,
                name=normalized_name,
                slug=normalized_slug,
                source_url="local",
                source_path=storage_path,
                license_name=license_name,
                license_url=license_url,
                status=LifecycleStatus.ACTIVE,
            )
            self.session.add(asset)
            await self.session.flush()
        else:
            asset.asset_type = normalized_asset_type
            asset.name = normalized_name
            asset.slug = normalized_slug
            asset.source_url = "local"
            asset.source_path = storage_path
            asset.license_name = license_name
            asset.license_url = license_url
            asset.status = LifecycleStatus.ACTIVE
            await self.session.flush()

        self._write_asset_manifest(
            asset.id,
            {
                "channel_slug": self._normalize_text(channel_slug),
                "topic": self._normalize_text(topic),
                "tags": normalized_tags,
                "is_default": asset.slug == _DEFAULT_ASSET_SLUG,
                "source_path": self._display_storage_path(storage_path),
            },
        )
        return self._describe_asset(asset)

    async def select_local_asset(
        self,
        *,
        video_id: int,
        asset_id: int | None = None,
        asset_slug: str | None = None,
        channel_slug: str | None = None,
        topic: str | None = None,
        tags: list[str] | None = None,
    ) -> AssetSelectionResult:
        video = await self.session.get(Video, video_id)
        if video is None:
            raise ValueError(f"Video {video_id} not found")

        if video.stage_status in _PREVIEW_LOCKED_STAGES:
            if asset_id is not None and video.asset_id == asset_id:
                asset = await self._get_asset_by_id(asset_id)
                if asset is None:
                    raise ValueError(f"Asset {asset_id} not found")
                self._ensure_supported_background_asset(
                    Path(asset.source_path) if asset.source_path else None,
                    asset.asset_type,
                )
                return self._build_selection_result(video_id=video.id, asset=asset)
            raise ValueError("Asset can only be changed before preview is generated")

        asset = await self._resolve_asset_choice(
            asset_id=asset_id,
            asset_slug=asset_slug,
            channel_slug=channel_slug,
            topic=topic,
            tags=tags,
        )
        if (
            asset is None
            and asset_id is None
            and asset_slug is None
            and channel_slug is None
            and topic is None
            and tags is None
            and video.asset_id is not None
        ):
            asset = await self._get_asset_by_id(video.asset_id)
        if asset is None:
            asset = await self._get_or_create_default_asset()
        self._ensure_supported_background_asset(
            Path(asset.source_path) if asset.source_path else None,
            asset.asset_type,
        )

        if video.stage_status not in {VideoStageStatus.CAPTION_DONE, VideoStageStatus.ASSET_READY}:
            raise ValueError("Asset can only be selected after captions are generated")

        video.asset_id = asset.id
        video.stage_status = VideoStageStatus.ASSET_READY
        await self.session.flush()
        return self._build_selection_result(video_id=video.id, asset=asset)

    def describe_asset(self, asset: AssetPool | None) -> AssetPoolRecord | None:
        if asset is None:
            return None
        return self._describe_asset(asset)

    async def _resolve_asset_choice(
        self,
        *,
        asset_id: int | None,
        asset_slug: str | None,
        channel_slug: str | None,
        topic: str | None,
        tags: list[str] | None,
    ) -> AssetPool | None:
        if asset_id is not None:
            asset = await self._get_asset_by_id(asset_id)
            if asset is None:
                raise ValueError(f"Asset {asset_id} not found")
            return asset

        if asset_slug is not None:
            statement = select(AssetPool).where(AssetPool.slug == asset_slug, AssetPool.status == LifecycleStatus.ACTIVE)
            asset = await self.session.scalar(statement)
            if asset is None:
                raise ValueError(f"Asset slug {asset_slug} not found")
            return asset

        assets = await self.list_assets(channel_slug=channel_slug, topic=topic, tags=tags)
        if not assets:
            return None

        default_asset = next((asset for asset in assets if asset.is_default), None)
        if channel_slug or topic or tags:
            for record in assets:
                if not record.is_default:
                    return await self._get_asset_by_id(record.asset_id)
        if default_asset is not None:
            return await self._get_asset_by_id(default_asset.asset_id)
        return await self._get_asset_by_id(assets[0].asset_id)

    async def _get_asset_by_id(self, asset_id: int) -> AssetPool | None:
        statement = select(AssetPool).where(AssetPool.id == asset_id)
        return await self.session.scalar(statement)

    async def _get_or_create_default_asset(self) -> AssetPool:
        statement = select(AssetPool).where(AssetPool.slug == _DEFAULT_ASSET_SLUG)
        asset = await self.session.scalar(statement)
        if asset is not None:
            if asset.source_path:
                path = Path(asset.source_path)
                if not path.exists():
                    self._generate_placeholder_asset(path)
            return asset

        asset_path = self.settings.asset_pool_path / "system" / "default-background.png"
        self._generate_placeholder_asset(asset_path)
        asset = AssetPool(
            asset_type="background_image",
            name=_DEFAULT_ASSET_NAME,
            slug=_DEFAULT_ASSET_SLUG,
            source_url="local",
            source_path=str(asset_path.resolve()),
            license_name="generated-local",
            license_url="local",
            status=LifecycleStatus.ACTIVE,
        )
        self.session.add(asset)
        await self.session.flush()
        self._write_asset_manifest(
            asset.id,
            {
                "channel_slug": None,
                "topic": None,
                "tags": [],
                "is_default": True,
                "source_path": self._display_storage_path(asset.source_path),
            },
        )
        return asset

    def _build_selection_result(self, *, video_id: int, asset: AssetPool) -> AssetSelectionResult:
        record = self._describe_asset(asset)
        return AssetSelectionResult(
            video_id=video_id,
            asset_id=record.asset_id,
            asset_path=record.source_path or "",
            asset_name=record.name,
            asset_slug=record.slug,
            asset_type=record.asset_type,
            channel_slug=record.channel_slug,
            topic=record.topic,
            tags=record.tags,
        )

    def _describe_asset(self, asset: AssetPool) -> AssetPoolRecord:
        manifest = self._read_asset_manifest().get(str(asset.id), {})
        tags = self._normalize_tags(manifest.get("tags"))
        source_path = self._display_storage_path(asset.source_path)
        return AssetPoolRecord(
            asset_id=asset.id,
            asset_type=asset.asset_type,
            name=asset.name,
            slug=asset.slug,
            source_path=source_path,
            license_name=asset.license_name,
            license_url=asset.license_url,
            status=asset.status.value if hasattr(asset.status, "value") else str(asset.status),
            channel_slug=self._normalize_text(manifest.get("channel_slug")),
            topic=self._normalize_text(manifest.get("topic")),
            tags=tags or None,
            is_default=bool(manifest.get("is_default")) or asset.slug == _DEFAULT_ASSET_SLUG,
        )

    def _matches_filters(
        self,
        asset: AssetPoolRecord,
        *,
        channel_slug: str | None,
        topic: str | None,
        tags: list[str] | None,
    ) -> bool:
        requested_tags = self._normalize_tags(tags)
        if channel_slug:
            asset_channel_slug = self._normalize_text(asset.channel_slug)
            if asset_channel_slug and asset_channel_slug != self._normalize_text(channel_slug):
                return False
            if not asset_channel_slug and not asset.is_default:
                return False
        if topic:
            asset_topic = self._normalize_text(asset.topic)
            requested_topic = self._normalize_text(topic)
            if asset_topic and asset_topic != requested_topic and requested_topic not in asset_topic and asset_topic not in requested_topic:
                return False
            if not asset_topic and not asset.is_default:
                return False
        if requested_tags:
            asset_tags = set(self._normalize_tags(asset.tags))
            if asset_tags and not asset_tags.intersection(requested_tags):
                return False
            if not asset_tags and not asset.is_default:
                return False
        return True

    def _read_asset_manifest(self) -> dict[str, dict[str, object]]:
        manifest_path = self._manifest_path()
        if not manifest_path.exists():
            return {}
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        manifest: dict[str, dict[str, object]] = {}
        for key, value in payload.items():
            if isinstance(key, str) and isinstance(value, dict):
                manifest[key] = value
        return manifest

    def _write_asset_manifest(self, asset_id: int, metadata: dict[str, object]) -> None:
        manifest = self._read_asset_manifest()
        manifest[str(asset_id)] = metadata
        manifest_path = self._manifest_path()
        ensure_parent_dir(manifest_path)
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def _manifest_path(self) -> Path:
        return self.settings.asset_pool_path / _ASSET_MANIFEST_FILENAME

    def _resolve_asset_path(self, relative_path: str) -> Path:
        requested_path = Path(relative_path)
        if requested_path.is_absolute():
            raise ValueError("Asset path must be relative to storage/assets")

        parts = requested_path.parts
        if len(parts) >= 2 and parts[0].lower() == "storage" and parts[1].lower() == "assets":
            requested_path = Path(*parts[2:])
            if not requested_path.parts:
                raise ValueError("Asset path must point to a file inside storage/assets")

        asset_root = self.settings.asset_pool_path.resolve()
        resolved_path = (asset_root / requested_path).resolve()
        try:
            resolved_path.relative_to(asset_root)
        except ValueError as exc:
            raise ValueError("Asset path must stay within storage/assets") from exc

        if not resolved_path.exists() or not resolved_path.is_file():
            raise ValueError("Asset file not found")

        if resolved_path.suffix.lower() == ".mp4":
            raise ValueError("Background video assets (.mp4) are not supported yet")

        if resolved_path.suffix.lower() not in _ALLOWED_ASSET_SUFFIXES:
            raise ValueError("Unsupported asset file type")

        return resolved_path

    def _ensure_supported_background_asset(self, path: Path | None, asset_type: str | None) -> None:
        if path is not None and path.suffix.lower() == ".mp4":
            raise ValueError("Background video assets (.mp4) are not supported yet")
        if (asset_type or "").strip().lower() == "background_video":
            raise ValueError("Background video assets (.mp4) are not supported yet")

    def _storage_relative_path(self, path: Path) -> str:
        storage_root = self.settings.local_storage_path.resolve().parent
        return str(path.resolve().relative_to(storage_root))

    def _display_storage_path(self, path_value: str | None) -> str | None:
        if not path_value:
            return None
        try:
            path = Path(path_value).resolve()
            storage_root = self.settings.local_storage_path.resolve().parent
            return path.relative_to(storage_root).as_posix()
        except Exception:
            return path_value

    def _normalize_asset_type(self, asset_type: str | None, resolved_path: Path) -> str:
        if asset_type:
            return asset_type.strip() or "background_image"
        if resolved_path.suffix.lower() == ".mp4":
            return "background_video"
        return "background_image"

    def _normalize_slug(self, value: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
        return slug or "asset"

    def _normalize_text(self, value: object | None) -> str | None:
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

    def _generate_placeholder_asset(self, asset_path: Path) -> None:
        ensure_parent_dir(asset_path)
        command = [
            self.settings.ffmpeg_path,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=0f172a:s=1080x1920:d=1",
            "-frames:v",
            "1",
            str(asset_path),
        ]
        run_command(command)

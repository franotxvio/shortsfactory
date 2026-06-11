from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.models.core import AssetPool, Video
from app.models.enums import LifecycleStatus, VideoStageStatus
from app.services.media_utils import ensure_parent_dir, run_command


@dataclass(slots=True)
class AssetSelectionResult:
    video_id: int
    asset_id: int
    asset_path: str


class AssetPoolService:
    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()

    async def select_local_asset(self, *, video_id: int) -> AssetSelectionResult:
        video = await self.session.get(Video, video_id)
        if video is None:
            raise ValueError(f"Video {video_id} not found")

        asset = await self._get_or_create_default_asset()
        video.asset_id = asset.id
        video.stage_status = VideoStageStatus.ASSET_READY
        await self.session.flush()
        return AssetSelectionResult(video_id=video.id, asset_id=asset.id, asset_path=str(asset.source_path))

    async def _get_or_create_default_asset(self) -> AssetPool:
        statement = select(AssetPool).where(AssetPool.status == LifecycleStatus.ACTIVE).order_by(AssetPool.id.asc())
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
            name="Default Background",
            slug="system-default-background",
            source_url="local",
            source_path=str(asset_path),
            license_name="generated-local",
            license_url="local",
            status=LifecycleStatus.ACTIVE,
        )
        self.session.add(asset)
        await self.session.flush()
        return asset

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


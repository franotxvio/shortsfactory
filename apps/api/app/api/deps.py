from collections.abc import AsyncIterator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_sessionmaker
from app.services.video_production import VideoProductionService
from app.services.script_engine import ScriptEngineService


async def get_async_session() -> AsyncIterator[AsyncSession]:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        yield session


def get_script_engine_service(
    session: AsyncSession = Depends(get_async_session),
) -> ScriptEngineService:
    return ScriptEngineService(session=session)


def get_video_production_service(
    session: AsyncSession = Depends(get_async_session),
) -> VideoProductionService:
    return VideoProductionService(session=session)

import asyncio
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.internal_scripts import router as internal_scripts_router
from app.api.routes.internal_videos import router as internal_videos_router
from app.core.config import get_settings
from app.core.db import close_engine, get_engine
from app.core.redis import close_redis_client, get_redis_client


def configure_windows_event_loop_policy() -> None:
    if sys.platform.startswith("win") and hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


configure_windows_event_loop_policy()


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.settings = get_settings()
    app.state.db_engine = get_engine()
    app.state.redis = get_redis_client()
    yield
    await close_redis_client()
    await close_engine()


app = FastAPI(title=get_settings().app_name, debug=get_settings().app_debug, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_allow_origin_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(internal_scripts_router, prefix="/internal")
app.include_router(internal_videos_router, prefix="/internal")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}

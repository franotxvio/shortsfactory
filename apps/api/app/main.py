from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes.internal_scripts import router as internal_scripts_router
from app.core.config import get_settings
from app.core.db import close_engine, get_engine
from app.core.redis import close_redis_client, get_redis_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.settings = get_settings()
    app.state.db_engine = get_engine()
    app.state.redis = get_redis_client()
    yield
    await close_redis_client()
    await close_engine()


app = FastAPI(title=get_settings().app_name, debug=get_settings().app_debug, lifespan=lifespan)
app.include_router(internal_scripts_router, prefix="/internal")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}

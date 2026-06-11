from contextlib import asynccontextmanager

from fastapi import FastAPI

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


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}

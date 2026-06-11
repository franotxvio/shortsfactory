from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import psycopg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


API_ROOT = Path(__file__).resolve().parents[1]
ADMIN_DSN = "postgresql://shortsfactory:shortsfactory@localhost:5433/postgres"
CORE_TABLES = [
    "scripts",
    "videos",
    "channels",
    "cost_logs",
    "llm_cache",
    "similarity_checks",
    "content_embeddings",
    "cost_budget",
    "asset_pool",
    "video_patterns",
    "weak_patterns",
    "winning_patterns",
]


@pytest.fixture(scope="session")
def temp_database_name() -> str:
    return f"shortsfactory_script_engine_{uuid.uuid4().hex[:8]}"


@pytest.fixture(scope="session")
def temp_database_url(temp_database_name: str) -> str:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute(f'DROP DATABASE IF EXISTS "{temp_database_name}"')
            cursor.execute(f'CREATE DATABASE "{temp_database_name}"')

    database_url = f"postgresql+asyncpg://shortsfactory:shortsfactory@localhost:5433/{temp_database_name}"
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=API_ROOT, env=env, check=True)
    return database_url


@pytest.fixture()
async def db_session(temp_database_url: str):
    engine = create_async_engine(temp_database_url, pool_pre_ping=True)
    async with engine.begin() as connection:
        tables_sql = ", ".join(CORE_TABLES)
        await connection.execute(text(f"TRUNCATE {tables_sql} RESTART IDENTITY CASCADE"))

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def _drop_temp_database(temp_database_name: str, temp_database_url: str):
    yield
    with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()",
                (temp_database_name,),
            )
            cursor.execute(f'DROP DATABASE IF EXISTS "{temp_database_name}"')

from sqlalchemy.schema import CreateTable
from sqlalchemy.dialects import postgresql

from app.models.base import Base
import app.models.core  # noqa: F401


def test_core_tables_registered_in_metadata() -> None:
    expected_tables = {
        "channels",
        "videos",
        "scripts",
        "cost_logs",
        "llm_cache",
        "asset_pool",
        "video_patterns",
        "weak_patterns",
        "winning_patterns",
        "content_embeddings",
        "similarity_checks",
        "cost_budget",
    }

    assert expected_tables.issubset(set(Base.metadata.tables))


def test_core_tables_compile_for_postgresql() -> None:
    dialect = postgresql.dialect()

    for table in Base.metadata.sorted_tables:
        str(CreateTable(table).compile(dialect=dialect))

    assert Base.metadata.tables["content_embeddings"].c.embedding.type.dim == 1536

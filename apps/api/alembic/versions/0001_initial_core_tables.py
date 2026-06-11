"""initial core tables

Revision ID: 0001_initial_core_tables
Revises:
Create Date: 2026-06-11 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector


# revision identifiers, used by Alembic.
revision = "0001_initial_core_tables"
down_revision = None
branch_labels = None
depends_on = None

lifecycle_status = sa.Enum("active", "inactive", "archived", name="lifecycle_status")
workflow_status = sa.Enum(
    "draft",
    "pending_review",
    "approved",
    "rejected",
    "completed",
    name="workflow_status",
)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "channels",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=160), nullable=False),
        sa.Column("status", lifecycle_status, server_default="active", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_channels")),
        sa.UniqueConstraint("slug", name=op.f("uq_channels_slug")),
    )

    op.create_table(
        "videos",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("channel_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=160), nullable=False),
        sa.Column("status", workflow_status, server_default="draft", nullable=False),
        sa.Column("target_duration_seconds", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"], name=op.f("fk_videos_channel_id_channels"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_videos")),
        sa.UniqueConstraint("channel_id", "slug", name="uq_videos_channel_id_slug"),
    )
    op.create_index("ix_videos_channel_id", "videos", ["channel_id"], unique=False)
    op.create_index("ix_videos_status", "videos", ["status"], unique=False)

    op.create_table(
        "scripts",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("video_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", workflow_status, server_default="draft", nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["video_id"], ["videos.id"], name=op.f("fk_scripts_video_id_videos"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scripts")),
        sa.UniqueConstraint("video_id", "version", name="uq_scripts_video_id_version"),
    )
    op.create_index("ix_scripts_video_id", "scripts", ["video_id"], unique=False)
    op.create_index("ix_scripts_status", "scripts", ["status"], unique=False)

    op.create_table(
        "cost_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True, nullable=False),
        sa.Column("video_id", sa.Integer(), nullable=True),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("operation", sa.String(length=64), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("cost_usd", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column("currency", sa.String(length=8), server_default="USD", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["video_id"], ["videos.id"], name=op.f("fk_cost_logs_video_id_videos"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cost_logs")),
    )
    op.create_index("ix_cost_logs_video_id", "cost_logs", ["video_id"], unique=False)
    op.create_index("ix_cost_logs_provider", "cost_logs", ["provider"], unique=False)

    op.create_table(
        "llm_cache",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("cache_key", sa.String(length=255), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("prompt_hash", sa.String(length=64), nullable=False),
        sa.Column("response_text", sa.Text(), nullable=True),
        sa.Column("response_json", sa.dialects.postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_llm_cache")),
        sa.UniqueConstraint("cache_key", name=op.f("uq_llm_cache_cache_key")),
        sa.UniqueConstraint("content_hash", name=op.f("uq_llm_cache_content_hash")),
    )
    op.create_index("ix_llm_cache_provider_model", "llm_cache", ["provider", "model"], unique=False)

    op.create_table(
        "asset_pool",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("asset_type", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=160), nullable=False),
        sa.Column("source_url", sa.String(length=1024), nullable=True),
        sa.Column("source_path", sa.String(length=1024), nullable=True),
        sa.Column("license_name", sa.String(length=128), nullable=False),
        sa.Column("license_url", sa.String(length=1024), nullable=True),
        sa.Column("status", lifecycle_status, server_default="active", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_asset_pool")),
        sa.UniqueConstraint("slug", name=op.f("uq_asset_pool_slug")),
    )
    op.create_index("ix_asset_pool_asset_type", "asset_pool", ["asset_type"], unique=False)
    op.create_index("ix_asset_pool_status", "asset_pool", ["status"], unique=False)

    op.create_table(
        "video_patterns",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("pattern_key", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("pattern_type", sa.String(length=64), nullable=False),
        sa.Column("score", sa.Numeric(precision=8, scale=4), nullable=False),
        sa.Column("status", lifecycle_status, server_default="active", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_video_patterns")),
        sa.UniqueConstraint("pattern_key", name=op.f("uq_video_patterns_pattern_key")),
    )
    op.create_index("ix_video_patterns_pattern_type", "video_patterns", ["pattern_type"], unique=False)
    op.create_index("ix_video_patterns_status", "video_patterns", ["status"], unique=False)

    op.create_table(
        "weak_patterns",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("pattern_key", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("status", lifecycle_status, server_default="active", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_weak_patterns")),
        sa.UniqueConstraint("pattern_key", name=op.f("uq_weak_patterns_pattern_key")),
    )
    op.create_index("ix_weak_patterns_status", "weak_patterns", ["status"], unique=False)

    op.create_table(
        "winning_patterns",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("pattern_key", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("evidence", sa.dialects.postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", lifecycle_status, server_default="active", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_winning_patterns")),
        sa.UniqueConstraint("pattern_key", name=op.f("uq_winning_patterns_pattern_key")),
    )
    op.create_index("ix_winning_patterns_status", "winning_patterns", ["status"], unique=False)

    op.create_table(
        "content_embeddings",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_content_embeddings")),
        sa.UniqueConstraint("content_hash", name=op.f("uq_content_embeddings_content_hash")),
        sa.UniqueConstraint("source_type", "source_id", name="uq_content_embeddings_source_type_source_id"),
    )
    op.create_index("ix_content_embeddings_source_type", "content_embeddings", ["source_type"], unique=False)
    op.create_index(
        "ix_content_embeddings_embedding_hnsw",
        "content_embeddings",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    op.create_table(
        "similarity_checks",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("video_id", sa.Integer(), nullable=False),
        sa.Column("content_embedding_id", sa.Integer(), nullable=True),
        sa.Column("threshold", sa.Numeric(precision=6, scale=4), nullable=False),
        sa.Column("similarity_score", sa.Numeric(precision=6, scale=4), nullable=False),
        sa.Column("status", workflow_status, server_default="pending_review", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["video_id"], ["videos.id"], name=op.f("fk_similarity_checks_video_id_videos"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["content_embedding_id"],
            ["content_embeddings.id"],
            name=op.f("fk_similarity_checks_content_embedding_id_content_embeddings"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_similarity_checks")),
    )
    op.create_index("ix_similarity_checks_video_id", "similarity_checks", ["video_id"], unique=False)
    op.create_index("ix_similarity_checks_status", "similarity_checks", ["status"], unique=False)

    op.create_table(
        "cost_budget",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("scope", sa.String(length=64), nullable=False),
        sa.Column("budget_usd", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("spent_usd", sa.Numeric(precision=12, scale=4), server_default="0", nullable=False),
        sa.Column("currency", sa.String(length=8), server_default="USD", nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", lifecycle_status, server_default="active", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cost_budget")),
        sa.UniqueConstraint("scope", name=op.f("uq_cost_budget_scope")),
    )
    op.create_index("ix_cost_budget_status", "cost_budget", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_cost_budget_status", table_name="cost_budget")
    op.drop_table("cost_budget")

    op.drop_index("ix_similarity_checks_status", table_name="similarity_checks")
    op.drop_index("ix_similarity_checks_video_id", table_name="similarity_checks")
    op.drop_table("similarity_checks")

    op.drop_index("ix_content_embeddings_embedding_hnsw", table_name="content_embeddings")
    op.drop_index("ix_content_embeddings_source_type", table_name="content_embeddings")
    op.drop_table("content_embeddings")

    op.drop_index("ix_winning_patterns_status", table_name="winning_patterns")
    op.drop_table("winning_patterns")

    op.drop_index("ix_weak_patterns_status", table_name="weak_patterns")
    op.drop_table("weak_patterns")

    op.drop_index("ix_video_patterns_status", table_name="video_patterns")
    op.drop_index("ix_video_patterns_pattern_type", table_name="video_patterns")
    op.drop_table("video_patterns")

    op.drop_index("ix_asset_pool_status", table_name="asset_pool")
    op.drop_index("ix_asset_pool_asset_type", table_name="asset_pool")
    op.drop_table("asset_pool")

    op.drop_index("ix_llm_cache_provider_model", table_name="llm_cache")
    op.drop_table("llm_cache")

    op.drop_index("ix_cost_logs_provider", table_name="cost_logs")
    op.drop_index("ix_cost_logs_video_id", table_name="cost_logs")
    op.drop_table("cost_logs")

    op.drop_index("ix_scripts_status", table_name="scripts")
    op.drop_index("ix_scripts_video_id", table_name="scripts")
    op.drop_table("scripts")

    op.drop_index("ix_videos_status", table_name="videos")
    op.drop_index("ix_videos_channel_id", table_name="videos")
    op.drop_table("videos")

    op.drop_table("channels")

    workflow_status.drop(op.get_bind(), checkfirst=True)
    lifecycle_status.drop(op.get_bind(), checkfirst=True)

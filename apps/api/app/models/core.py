from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector

from app.models.base import Base, TimestampMixin
from app.models.enums import (
    LifecycleStatus,
    VideoStageStatus,
    WorkflowStatus,
    lifecycle_status_type,
    video_stage_status_type,
    workflow_status_type,
)


class Channel(TimestampMixin, Base):
    __tablename__ = "channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    status: Mapped[LifecycleStatus] = mapped_column(
        lifecycle_status_type(),
        nullable=False,
        default=LifecycleStatus.ACTIVE,
        server_default=LifecycleStatus.ACTIVE.value,
    )

    videos: Mapped[list["Video"]] = relationship(back_populates="channel", cascade="all, delete-orphan")


class Video(TimestampMixin, Base):
    __tablename__ = "videos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel_id: Mapped[int] = mapped_column(
        ForeignKey("channels.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[WorkflowStatus] = mapped_column(
        workflow_status_type(),
        nullable=False,
        default=WorkflowStatus.DRAFT,
        server_default=WorkflowStatus.DRAFT.value,
    )
    stage_status: Mapped[VideoStageStatus] = mapped_column(
        video_stage_status_type(),
        nullable=False,
        default=VideoStageStatus.DRAFT,
        server_default=VideoStageStatus.DRAFT.value,
    )
    target_duration_seconds: Mapped[int | None] = mapped_column(Integer)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("asset_pool.id", ondelete="SET NULL"))
    audio_path: Mapped[str | None] = mapped_column(String(1024))
    caption_path: Mapped[str | None] = mapped_column(String(1024))
    preview_path: Mapped[str | None] = mapped_column(String(1024))
    final_path: Mapped[str | None] = mapped_column(String(1024))
    preview_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    channel: Mapped[Channel] = relationship(back_populates="videos")
    scripts: Mapped[list["Script"]] = relationship(back_populates="video", cascade="all, delete-orphan")
    asset: Mapped[AssetPool | None] = relationship("AssetPool")

    __table_args__ = (
        UniqueConstraint("channel_id", "slug", name="uq_videos_channel_id_slug"),
        Index("ix_videos_channel_id", "channel_id"),
        Index("ix_videos_status", "status"),
        Index("ix_videos_stage_status", "stage_status"),
    )


class Script(TimestampMixin, Base):
    __tablename__ = "scripts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    video_id: Mapped[int] = mapped_column(
        ForeignKey("videos.id", ondelete="CASCADE"),
        nullable=False,
    )
    topic: Mapped[str | None] = mapped_column(String(255))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[WorkflowStatus] = mapped_column(
        workflow_status_type(),
        nullable=False,
        default=WorkflowStatus.DRAFT,
        server_default=WorkflowStatus.DRAFT.value,
    )
    idea: Mapped[str | None] = mapped_column(Text)
    hook: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    policy_risk_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    policy_decision: Mapped[str | None] = mapped_column(String(32))
    generation_payload: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    llm_model: Mapped[str | None] = mapped_column(String(128))
    llm_cache_key: Mapped[str | None] = mapped_column(String(255))
    llm_input_hash: Mapped[str | None] = mapped_column(String(64))

    video: Mapped[Video] = relationship(back_populates="scripts")

    __table_args__ = (
        UniqueConstraint("video_id", "version", name="uq_scripts_video_id_version"),
        Index("ix_scripts_video_id", "video_id"),
        Index("ix_scripts_status", "status"),
        Index("ix_scripts_policy_risk_score", "policy_risk_score"),
    )


class CostLog(TimestampMixin, Base):
    __tablename__ = "cost_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    video_id: Mapped[int | None] = mapped_column(ForeignKey("videos.id", ondelete="SET NULL"))
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(128))
    model: Mapped[str | None] = mapped_column(String(128))
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    estimated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD", server_default="USD")

    __table_args__ = (
        Index("ix_cost_logs_video_id", "video_id"),
        Index("ix_cost_logs_provider", "provider"),
    )


class LLMCache(TimestampMixin, Base):
    __tablename__ = "llm_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    cache_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_text: Mapped[str | None] = mapped_column(Text)
    response_json: Mapped[dict[str, object] | list[object] | None] = mapped_column(JSONB)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_llm_cache_provider_model", "provider", "model"),
        Index("ix_llm_cache_content_hash", "content_hash"),
    )


class AssetPool(TimestampMixin, Base):
    __tablename__ = "asset_pool"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_type: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    source_url: Mapped[str | None] = mapped_column(String(1024))
    source_path: Mapped[str | None] = mapped_column(String(1024))
    license_name: Mapped[str] = mapped_column(String(128), nullable=False)
    license_url: Mapped[str | None] = mapped_column(String(1024))
    status: Mapped[LifecycleStatus] = mapped_column(
        lifecycle_status_type(),
        nullable=False,
        default=LifecycleStatus.ACTIVE,
        server_default=LifecycleStatus.ACTIVE.value,
    )

    __table_args__ = (
        Index("ix_asset_pool_asset_type", "asset_type"),
        Index("ix_asset_pool_status", "status"),
    )


class VideoPattern(TimestampMixin, Base):
    __tablename__ = "video_patterns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pattern_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    pattern_type: Mapped[str] = mapped_column(String(64), nullable=False)
    score: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, default=0)
    status: Mapped[LifecycleStatus] = mapped_column(
        lifecycle_status_type(),
        nullable=False,
        default=LifecycleStatus.ACTIVE,
        server_default=LifecycleStatus.ACTIVE.value,
    )

    __table_args__ = (
        Index("ix_video_patterns_pattern_type", "pattern_type"),
        Index("ix_video_patterns_status", "status"),
    )


class WeakPattern(TimestampMixin, Base):
    __tablename__ = "weak_patterns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pattern_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[LifecycleStatus] = mapped_column(
        lifecycle_status_type(),
        nullable=False,
        default=LifecycleStatus.ACTIVE,
        server_default=LifecycleStatus.ACTIVE.value,
    )

    __table_args__ = (
        Index("ix_weak_patterns_status", "status"),
    )


class WinningPattern(TimestampMixin, Base):
    __tablename__ = "winning_patterns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pattern_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[dict[str, object] | list[object] | None] = mapped_column(JSONB)
    status: Mapped[LifecycleStatus] = mapped_column(
        lifecycle_status_type(),
        nullable=False,
        default=LifecycleStatus.ACTIVE,
        server_default=LifecycleStatus.ACTIVE.value,
    )

    __table_args__ = (
        Index("ix_winning_patterns_status", "status"),
    )


class ContentEmbedding(TimestampMixin, Base):
    __tablename__ = "content_embeddings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_id: Mapped[str] = mapped_column(String(128), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(1536), nullable=False)

    __table_args__ = (
        UniqueConstraint("source_type", "source_id", name="uq_content_embeddings_source_type_source_id"),
        Index("ix_content_embeddings_source_type", "source_type"),
        Index(
            "ix_content_embeddings_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


class SimilarityCheck(TimestampMixin, Base):
    __tablename__ = "similarity_checks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    video_id: Mapped[int] = mapped_column(
        ForeignKey("videos.id", ondelete="CASCADE"),
        nullable=False,
    )
    content_embedding_id: Mapped[int | None] = mapped_column(
        ForeignKey("content_embeddings.id", ondelete="SET NULL")
    )
    threshold: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    similarity_score: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    status: Mapped[WorkflowStatus] = mapped_column(
        workflow_status_type(),
        nullable=False,
        default=WorkflowStatus.PENDING_REVIEW,
        server_default=WorkflowStatus.PENDING_REVIEW.value,
    )

    __table_args__ = (
        Index("ix_similarity_checks_video_id", "video_id"),
        Index("ix_similarity_checks_status", "status"),
    )


class CostBudget(TimestampMixin, Base):
    __tablename__ = "cost_budget"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scope: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    budget_usd: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    spent_usd: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False, default=0, server_default="0")
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD", server_default="USD")
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[LifecycleStatus] = mapped_column(
        lifecycle_status_type(),
        nullable=False,
        default=LifecycleStatus.ACTIVE,
        server_default=LifecycleStatus.ACTIVE.value,
    )

    __table_args__ = (
        Index("ix_cost_budget_status", "status"),
    )

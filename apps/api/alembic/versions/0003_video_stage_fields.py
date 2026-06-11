"""add video stage fields

Revision ID: 0003_video_stage_fields
Revises: 0002_script_engine_fields
Create Date: 2026-06-11 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0003_video_stage_fields"
down_revision = "0002_script_engine_fields"
branch_labels = None
depends_on = None

video_stage_status = sa.Enum(
    "draft",
    "script_approved",
    "tts_done",
    "caption_done",
    "asset_ready",
    "preview_ready",
    "preview_approved",
    "final_rendered",
    name="video_stage_status",
)


def upgrade() -> None:
    bind = op.get_bind()
    video_stage_status.create(bind, checkfirst=True)
    op.add_column(
        "videos",
        sa.Column(
            "stage_status",
            sa.Enum(
                "draft",
                "script_approved",
                "tts_done",
                "caption_done",
                "asset_ready",
                "preview_ready",
                "preview_approved",
                "final_rendered",
                name="video_stage_status",
                create_type=False,
            ),
            server_default="draft",
            nullable=False,
        ),
    )
    op.add_column("videos", sa.Column("asset_id", sa.Integer(), nullable=True))
    op.add_column("videos", sa.Column("audio_path", sa.String(length=1024), nullable=True))
    op.add_column("videos", sa.Column("caption_path", sa.String(length=1024), nullable=True))
    op.add_column("videos", sa.Column("preview_path", sa.String(length=1024), nullable=True))
    op.add_column("videos", sa.Column("final_path", sa.String(length=1024), nullable=True))
    op.add_column("videos", sa.Column("preview_approved_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key("fk_videos_asset_id_asset_pool", "videos", "asset_pool", ["asset_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_videos_stage_status", "videos", ["stage_status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_videos_stage_status", table_name="videos")
    op.drop_constraint("fk_videos_asset_id_asset_pool", "videos", type_="foreignkey")
    op.drop_column("videos", "preview_approved_at")
    op.drop_column("videos", "final_path")
    op.drop_column("videos", "preview_path")
    op.drop_column("videos", "caption_path")
    op.drop_column("videos", "audio_path")
    op.drop_column("videos", "asset_id")
    op.drop_column("videos", "stage_status")
    video_stage_status.drop(op.get_bind(), checkfirst=True)

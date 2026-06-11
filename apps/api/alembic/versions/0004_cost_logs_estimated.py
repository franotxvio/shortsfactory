"""add estimated flag to cost_logs

Revision ID: 0004_cost_logs_estimated
Revises: 0003_video_stage_fields
Create Date: 2026-06-11 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0004_cost_logs_estimated"
down_revision = "0003_video_stage_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cost_logs",
        sa.Column("estimated", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("cost_logs", "estimated")

"""add script engine fields

Revision ID: 0002_script_engine_fields
Revises: 0001_initial_core_tables
Create Date: 2026-06-11 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0002_script_engine_fields"
down_revision = "0001_initial_core_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("scripts", sa.Column("topic", sa.String(length=255), nullable=True))
    op.add_column("scripts", sa.Column("idea", sa.Text(), nullable=True))
    op.add_column("scripts", sa.Column("hook", sa.Text(), nullable=True))
    op.add_column("scripts", sa.Column("policy_risk_score", sa.Numeric(precision=5, scale=4), nullable=True))
    op.add_column("scripts", sa.Column("policy_decision", sa.String(length=32), nullable=True))
    op.add_column(
        "scripts",
        sa.Column("generation_payload", sa.dialects.postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("scripts", sa.Column("llm_model", sa.String(length=128), nullable=True))
    op.add_column("scripts", sa.Column("llm_cache_key", sa.String(length=255), nullable=True))
    op.add_column("scripts", sa.Column("llm_input_hash", sa.String(length=64), nullable=True))
    op.create_index("ix_scripts_policy_risk_score", "scripts", ["policy_risk_score"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_scripts_policy_risk_score", table_name="scripts")
    op.drop_column("scripts", "llm_input_hash")
    op.drop_column("scripts", "llm_cache_key")
    op.drop_column("scripts", "llm_model")
    op.drop_column("scripts", "generation_payload")
    op.drop_column("scripts", "policy_decision")
    op.drop_column("scripts", "policy_risk_score")
    op.drop_column("scripts", "hook")
    op.drop_column("scripts", "idea")
    op.drop_column("scripts", "topic")

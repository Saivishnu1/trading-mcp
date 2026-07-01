"""Migration staging tables for Turso → PostgreSQL data import.

Creates mirror tables in the migration.* schema:
  migration.trades              — mirrors zerodha.trades
  migration.recommendation_log  — mirrors journal.recommendation_log

These tables are used as a safe intermediate landing zone during the
one-time Turso data migration. After promotion they are truncated
but the schema is retained so the process can be replayed if needed.

Sessions and api_keys are NOT staged — they are ephemeral and start fresh
on the Oracle VM.

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-01 00:00:01.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # migration.trades  — identical columns to zerodha.trades
    # ------------------------------------------------------------------
    op.create_table(
        "trades",
        sa.Column("id",                      sa.Text(),    primary_key=True, nullable=False),
        sa.Column("symbol",                  sa.Text(),    nullable=False),
        sa.Column("trade_type",              sa.Text(),    nullable=False, server_default="EQUITY"),
        sa.Column("direction",               sa.Text(),    nullable=False),
        sa.Column("strategy",                sa.Text()),
        sa.Column("entry_price",             sa.Float(),   nullable=False),
        sa.Column("quantity",                sa.Integer()),
        sa.Column("entry_date",              sa.Text(),    nullable=False),
        sa.Column("entry_time",              sa.Text(),    nullable=False),
        sa.Column("rationale",               sa.Text()),
        sa.Column("stoploss",                sa.Float()),
        sa.Column("target",                  sa.Float()),
        sa.Column("risk_reward",             sa.Float()),
        sa.Column("regime",                  sa.Text()),
        sa.Column("signal",                  sa.Text()),
        sa.Column("risk_score",              sa.Integer()),
        sa.Column("analysis_snapshot",       sa.Text()),
        sa.Column("created_by",              sa.Text(),    nullable=False, server_default="MANUAL"),
        sa.Column("status",                  sa.Text(),    nullable=False, server_default="OPEN"),
        sa.Column("exit_price",              sa.Float()),
        sa.Column("exit_date",               sa.Text()),
        sa.Column("exit_time",               sa.Text()),
        sa.Column("exit_reason",             sa.Text()),
        sa.Column("pnl",                     sa.Float()),
        sa.Column("pnl_percent",             sa.Float()),
        sa.Column("holding_days",            sa.Integer()),
        sa.Column("tags",                    sa.Text()),
        sa.Column("notes",                   sa.Text()),
        sa.Column("risk_amount",             sa.Float()),
        sa.Column("capital_at_risk",         sa.Float()),
        sa.Column("portfolio_heat_at_entry", sa.Float()),
        sa.Column("external_id",             sa.Text()),
        sa.Column("created_at",              sa.Text(),    nullable=False),
        sa.Column("updated_at",              sa.Text(),    nullable=False),
        sa.Column("user_id",                 sa.Text()),
        schema="migration",
    )
    op.create_index("ix_migration_trades_symbol",  "trades", ["symbol"],  schema="migration")
    op.create_index("ix_migration_trades_user_id", "trades", ["user_id"], schema="migration")

    # ------------------------------------------------------------------
    # migration.recommendation_log  — identical columns to journal.recommendation_log
    # No check constraints on the staging table — we want raw data to land
    # even if a value is unexpected; validation happens in step 3.
    # ------------------------------------------------------------------
    op.create_table(
        "recommendation_log",
        sa.Column("id",                           sa.Text(), primary_key=True, nullable=False),
        sa.Column("timestamp",                    sa.Text(), nullable=False),
        sa.Column("symbol",                       sa.Text()),
        sa.Column("market_snapshot",              sa.Text()),
        sa.Column("mcp_facts",                    sa.Text()),
        sa.Column("user_action",                  sa.Text()),
        sa.Column("outcome_1d",                   sa.Float()),
        sa.Column("outcome_5d",                   sa.Float()),
        sa.Column("outcome_20d",                  sa.Float()),
        sa.Column("claude_reasoning_summary",     sa.Text()),
        sa.Column("recommendation_type",          sa.Text()),
        sa.Column("uncertainty_level",            sa.Text()),
        sa.Column("mcp_changed_decision",         sa.Integer()),
        sa.Column("would_have_acted_without_mcp", sa.Integer()),
        sa.Column("decision_quality",             sa.Text()),
        sa.Column("postmortem_helpful",           sa.Integer()),
        sa.Column("postmortem_why",               sa.Text()),
        sa.Column("postmortem_review_questions",  sa.Text()),
        sa.Column("bootstrap_period",             sa.Integer(), server_default=sa.text("1")),
        sa.Column("bias_contaminated",            sa.Integer(), server_default=sa.text("1")),
        sa.Column("baseline_no_mcp",              sa.Integer(), server_default=sa.text("0")),
        sa.Column("capture_mode",                 sa.Text(),    server_default="manual"),
        sa.Column("created_at",                   sa.Text(),    nullable=False),
        sa.Column("updated_at",                   sa.Text(),    nullable=False),
        sa.Column("user_id",                      sa.Text()),
        schema="migration",
    )
    op.create_index("ix_migration_rec_log_symbol",  "recommendation_log", ["symbol"],  schema="migration")
    op.create_index("ix_migration_rec_log_user_id", "recommendation_log", ["user_id"], schema="migration")


def downgrade() -> None:
    op.drop_table("recommendation_log", schema="migration")
    op.drop_table("trades",             schema="migration")

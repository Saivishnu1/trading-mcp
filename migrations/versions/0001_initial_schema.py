"""Initial schema — all tables from SQLite v7 ported to PostgreSQL.

Final schema layout:
  zerodha.trades              — trade journal (v1–v7 columns)
  journal.recommendation_log  — decision quality logger (Phase 22)
  auth.sessions               — Zerodha session tokens (ephemeral, never migrated)
  auth.api_keys               — MCP client API keys (ephemeral, never migrated)
  migration.alembic_version   — Alembic version table (managed by Alembic itself)

Sessions and api_keys are intentionally empty on first deploy.
They are ephemeral (24-hour Zerodha tokens) and regenerate on first login.
They are excluded from Turso data migration.

Views (clean_recommendations, baseline_decisions, bootstrap_records) are not
ported — they are derivable from table data and add downgrade complexity.

Revision ID: 0001
Revises: None
Create Date: 2026-07-01 00:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # zerodha.trades
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
        # v2: immutable entry-time sizing snapshots
        sa.Column("risk_amount",             sa.Float()),
        sa.Column("capital_at_risk",         sa.Float()),
        sa.Column("portfolio_heat_at_entry", sa.Float()),
        # v3: deduplication key for Zerodha auto-import
        sa.Column("external_id",             sa.Text()),
        sa.Column("created_at",              sa.Text(),    nullable=False),
        sa.Column("updated_at",              sa.Text(),    nullable=False),
        # v7: multi-user isolation
        sa.Column("user_id",                 sa.Text()),
        schema="zerodha",
    )
    op.create_index("ix_trades_symbol",      "trades", ["symbol"],      schema="zerodha")
    op.create_index("ix_trades_status",      "trades", ["status"],      schema="zerodha")
    op.create_index("ix_trades_entry_date",  "trades", ["entry_date"],  schema="zerodha")
    op.create_index("ix_trades_trade_type",  "trades", ["trade_type"],  schema="zerodha")
    op.create_index("ix_trades_external_id", "trades", ["external_id"], schema="zerodha")
    op.create_index("ix_trades_user_id",     "trades", ["user_id"],     schema="zerodha")

    # ------------------------------------------------------------------
    # journal.recommendation_log
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
        sa.CheckConstraint(
            "recommendation_type IN ("
            "'ENTER','EXIT','HOLD','AVOID','OBSERVE',"
            "'STAY_CASH','SIZE_REDUCE','TAKE_PROFIT','TIGHTEN_STOP','NONE')",
            name="valid_recommendation_type",
        ),
        sa.CheckConstraint(
            "uncertainty_level IN ('LOW','MEDIUM','HIGH')",
            name="valid_uncertainty_level",
        ),
        sa.CheckConstraint(
            "capture_mode IN ('manual','auto','baseline')",
            name="valid_capture_mode",
        ),
        schema="journal",
    )
    op.create_index("ix_recommendation_log_symbol",    "recommendation_log", ["symbol"],    schema="journal")
    op.create_index("ix_recommendation_log_timestamp", "recommendation_log", ["timestamp"], schema="journal")
    op.create_index("ix_recommendation_log_user_id",   "recommendation_log", ["user_id"],   schema="journal")

    # ------------------------------------------------------------------
    # auth.sessions
    # Intentionally starts empty — ephemeral Zerodha tokens regenerate
    # on first login. Not included in Turso data migration.
    # ------------------------------------------------------------------
    op.create_table(
        "sessions",
        sa.Column("id",         sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id",    sa.Text(),    nullable=False),
        sa.Column("enctoken",   sa.Text(),    nullable=False),
        sa.Column("created_at", sa.Text(),    nullable=False),
        sa.Column("last_used",  sa.Text(),    nullable=False),
        sa.Column("is_active",  sa.Integer(), nullable=False, server_default=sa.text("1")),
        schema="auth",
    )
    op.create_index("ix_sessions_user_id",   "sessions", ["user_id"],   schema="auth")
    op.create_index("ix_sessions_is_active", "sessions", ["is_active"], schema="auth")

    # ------------------------------------------------------------------
    # auth.api_keys
    # Intentionally starts empty — API keys regenerate on first login.
    # Not included in Turso data migration.
    # ------------------------------------------------------------------
    op.create_table(
        "api_keys",
        sa.Column("api_key",    sa.Text(),    primary_key=True, nullable=False),
        sa.Column("user_id",    sa.Text(),    nullable=False),
        sa.Column("created_at", sa.Text(),    nullable=False),
        sa.Column("last_used",  sa.Text()),
        sa.Column("is_active",  sa.Integer(), nullable=False, server_default=sa.text("1")),
        schema="auth",
    )
    op.create_index("ix_api_keys_user_id",   "api_keys", ["user_id"],   schema="auth")
    op.create_index("ix_api_keys_is_active", "api_keys", ["is_active"], schema="auth")


def downgrade() -> None:
    op.drop_table("api_keys",           schema="auth")
    op.drop_table("sessions",           schema="auth")
    op.drop_table("recommendation_log", schema="journal")
    op.drop_table("trades",             schema="zerodha")

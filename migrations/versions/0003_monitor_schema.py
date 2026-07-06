"""monitor.* schema — Phase 9A live position monitor with WhatsApp alerts.

Creates:
  monitor.users              — one row per monitored account (multi-tenant
                                schema, single user today)
  monitor.positions          — tracked open option positions, synced from
                                the broker on a schedule
  monitor.peaks              — running peak premium + trailing SL per position
  monitor.alerts             — WhatsApp alert history (for cooldown lookups
                                and get_recent_alerts())
  monitor.settings           — per-user alert thresholds and cooldowns
  monitor.session_state      — per-session market snapshot (open PCR/VIX/
                                walls) plus heartbeat timestamps used by
                                get_monitor_status() to detect a stale process
  monitor.instrument_cache   — resolved broker instrument_id -> symbol/
                                strike/expiry/option_type, with expiry via
                                expires_at (refreshed on every cache write)

The monitor schema itself is created idempotently in migrations/env.py
(MANAGED_SCHEMAS) before this migration runs, same as every other schema.

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-06 00:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # monitor.users
    # ------------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("id",             sa.Text(),    primary_key=True, nullable=False),
        sa.Column("name",           sa.Text(),    nullable=False),
        sa.Column("whatsapp_phone", sa.Text(),    nullable=False),
        sa.Column("callmebot_key",  sa.Text(),    nullable=False),
        sa.Column("broker_type",    sa.Text(),    nullable=False, server_default="zerodha+indmoney"),
        sa.Column("is_default",     sa.Boolean(), server_default=sa.text("false")),
        sa.Column("is_active",      sa.Boolean(), server_default=sa.text("true")),
        sa.Column("created_at",     sa.Text(),    nullable=False),
        sa.Column("updated_at",     sa.Text(),    nullable=False),
        schema="monitor",
    )

    # ------------------------------------------------------------------
    # monitor.positions
    # ------------------------------------------------------------------
    op.create_table(
        "positions",
        sa.Column("id",            sa.Text(),  primary_key=True, nullable=False),
        sa.Column("user_id",       sa.Text(),  nullable=False),
        sa.Column("broker",        sa.Text(),  nullable=False),
        sa.Column("symbol",        sa.Text(),  nullable=False),
        sa.Column("expiry",        sa.Text(),  nullable=False),
        sa.Column("strike",        sa.Float(), nullable=False),
        sa.Column("option_type",   sa.Text(),  nullable=False),
        sa.Column("exchange",      sa.Text(),  nullable=False),
        sa.Column("entry_premium", sa.Float(), nullable=False),
        sa.Column("qty",           sa.Integer(), nullable=False),
        sa.Column("status",        sa.Text(),  nullable=False, server_default="active"),
        sa.Column("created_at",    sa.Text(),  nullable=False),
        sa.Column("updated_at",    sa.Text(),  nullable=False),
        sa.CheckConstraint("option_type IN ('CE','PE')", name="valid_option_type"),
        sa.CheckConstraint("status IN ('active','closed')", name="valid_status"),
        schema="monitor",
    )
    op.create_index(
        "uq_monitor_positions_key", "positions",
        ["user_id", "broker", "symbol", "expiry", "strike", "option_type"],
        unique=True, schema="monitor",
    )

    # ------------------------------------------------------------------
    # monitor.peaks
    # ------------------------------------------------------------------
    op.create_table(
        "peaks",
        sa.Column("id",              sa.Text(),  primary_key=True, nullable=False),
        sa.Column("user_id",         sa.Text(),  nullable=False),
        sa.Column("position_id",     sa.Text(),  nullable=False),
        sa.Column("peak_premium",    sa.Float(), nullable=False),
        sa.Column("peak_at",         sa.Text(),  nullable=False),
        sa.Column("trailing_sl",     sa.Float(), nullable=False),
        sa.Column("trailing_sl_pct", sa.Float(), nullable=False),
        sa.Column("updated_at",      sa.Text(),  nullable=False),
        schema="monitor",
    )
    op.create_index("ix_monitor_peaks_position_id", "peaks", ["position_id"], schema="monitor")

    # ------------------------------------------------------------------
    # monitor.alerts
    # ------------------------------------------------------------------
    op.create_table(
        "alerts",
        sa.Column("id",           sa.Text(),    primary_key=True, nullable=False),
        sa.Column("user_id",      sa.Text(),    nullable=False),
        sa.Column("alert_type",   sa.Text(),    nullable=False),
        sa.Column("symbol",       sa.Text()),
        sa.Column("message",      sa.Text(),    nullable=False),
        sa.Column("delivered",    sa.Boolean(), server_default=sa.text("false")),
        sa.Column("delivered_at", sa.Text()),
        sa.Column("created_at",   sa.Text(),    nullable=False),
        schema="monitor",
    )
    op.create_index("ix_monitor_alerts_user_id", "alerts", ["user_id"], schema="monitor")

    # ------------------------------------------------------------------
    # monitor.settings
    # ------------------------------------------------------------------
    op.create_table(
        "settings",
        sa.Column("user_id",             sa.Text(),  primary_key=True, nullable=False),
        sa.Column("pcr_shift_threshold", sa.Float(), server_default=sa.text("0.3")),
        sa.Column("vix_spike_threshold", sa.Float(), server_default=sa.text("14.0")),
        sa.Column("profit_alert_pct",    sa.Float(), server_default=sa.text("0.50")),
        sa.Column("cooldown_trailing",   sa.Integer(), server_default=sa.text("300")),
        sa.Column("cooldown_pcr",        sa.Integer(), server_default=sa.text("900")),
        sa.Column("cooldown_vix",        sa.Integer(), server_default=sa.text("900")),
        sa.Column("cooldown_profit",     sa.Integer(), server_default=sa.text("86400")),
        sa.Column("updated_at",          sa.Text(), nullable=False),
        schema="monitor",
    )

    # ------------------------------------------------------------------
    # monitor.session_state
    # ------------------------------------------------------------------
    op.create_table(
        "session_state",
        sa.Column("user_id",             sa.Text(),  primary_key=True, nullable=False),
        sa.Column("open_pcr",            sa.Float()),
        sa.Column("open_vix",            sa.Float()),
        sa.Column("open_call_wall",      sa.Float()),
        sa.Column("open_put_wall",       sa.Float()),
        sa.Column("session_date",        sa.Text(), nullable=False),
        sa.Column("last_heartbeat",      sa.Text()),
        sa.Column("last_market_check",   sa.Text()),
        sa.Column("last_position_check", sa.Text()),
        sa.Column("last_alert_sent",     sa.Text()),
        sa.Column("updated_at",          sa.Text(), nullable=False),
        schema="monitor",
    )

    # ------------------------------------------------------------------
    # monitor.instrument_cache
    # ------------------------------------------------------------------
    op.create_table(
        "instrument_cache",
        sa.Column("broker",        sa.Text(),  primary_key=True, nullable=False),
        sa.Column("instrument_id", sa.Text(),  primary_key=True, nullable=False),
        sa.Column("symbol",        sa.Text(),  nullable=False),
        sa.Column("expiry",        sa.Text(),  nullable=False),
        sa.Column("strike",        sa.Float(), nullable=False),
        sa.Column("option_type",   sa.Text(),  nullable=False),
        sa.Column("exchange",      sa.Text(),  nullable=False),
        sa.Column("expires_at",    sa.Text(),  nullable=False),
        sa.Column("updated_at",    sa.Text(),  nullable=False),
        schema="monitor",
    )


def downgrade() -> None:
    op.drop_table("instrument_cache", schema="monitor")
    op.drop_table("session_state",    schema="monitor")
    op.drop_table("settings",         schema="monitor")
    op.drop_table("alerts",           schema="monitor")
    op.drop_table("peaks",            schema="monitor")
    op.drop_table("positions",        schema="monitor")
    op.drop_table("users",            schema="monitor")

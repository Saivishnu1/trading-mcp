"""Trailing-SL persistence (2026-07-11) — zerodha.trailing_sl_state.

Mutable current-SL snapshot for active trailing-SL orders, updated in place
on every ratchet. Lets a monitor/bot restart rehydrate in-flight trailing
tasks instead of silently losing them — see src/execution/trailing_sl.py.

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-11 00:00:02.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "trailing_sl_state",
        sa.Column("order_id",         sa.Text(),  primary_key=True, nullable=False),
        sa.Column("exchange",         sa.Text(),  nullable=False),
        sa.Column("security_id",      sa.Text(),  nullable=False),
        sa.Column("side",             sa.Text(),  nullable=False),
        sa.Column("broker",           sa.Text(),  nullable=False),
        sa.Column("trail_points",     sa.Float(), nullable=False),
        sa.Column("sl_trigger_price", sa.Float(), nullable=False),
        sa.Column("sl_limit_price",   sa.Float(), nullable=False),
        sa.Column("active",           sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("updated_at",       sa.Text(),  nullable=False),
        sa.CheckConstraint("side IN ('BUY','SELL')", name="valid_trailing_sl_side"),
        schema="zerodha",
    )
    op.create_index("ix_trailing_sl_state_active", "trailing_sl_state", ["active"], schema="zerodha")


def downgrade() -> None:
    op.drop_index("ix_trailing_sl_state_active", table_name="trailing_sl_state", schema="zerodha")
    op.drop_table("trailing_sl_state", schema="zerodha")

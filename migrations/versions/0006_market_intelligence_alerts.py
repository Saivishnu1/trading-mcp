"""Phase 9B — market intelligence alerts: macro/index-move reference values,
new alert thresholds/cooldown, and a severity label on monitor.alerts.

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-08 00:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("session_state", sa.Column("open_crude", sa.Float()), schema="monitor")
    op.add_column("session_state", sa.Column("open_gold", sa.Float()), schema="monitor")
    op.add_column("session_state", sa.Column("open_nifty", sa.Float()), schema="monitor")
    op.add_column("session_state", sa.Column("open_sensex", sa.Float()), schema="monitor")
    op.add_column("session_state", sa.Column("last_nifty_spot", sa.Float()), schema="monitor")
    op.add_column("session_state", sa.Column("last_sensex_spot", sa.Float()), schema="monitor")

    op.add_column("settings", sa.Column("crude_move_threshold", sa.Float(), server_default=sa.text("2.0")), schema="monitor")
    op.add_column("settings", sa.Column("gold_move_threshold", sa.Float(), server_default=sa.text("1.5")), schema="monitor")
    op.add_column("settings", sa.Column("nifty_move_threshold", sa.Float(), server_default=sa.text("1.0")), schema="monitor")
    op.add_column("settings", sa.Column("sensex_move_threshold", sa.Float(), server_default=sa.text("1.0")), schema="monitor")
    op.add_column("settings", sa.Column("risk_off_count_threshold", sa.Integer(), server_default=sa.text("3")), schema="monitor")
    op.add_column("settings", sa.Column("cooldown_macro", sa.Integer(), server_default=sa.text("1800")), schema="monitor")
    op.add_column("settings", sa.Column("cooldown_wall_break", sa.Integer(), server_default=sa.text("1800")), schema="monitor")

    op.add_column("alerts", sa.Column("severity", sa.Text(), server_default=sa.text("'medium'")), schema="monitor")


def downgrade() -> None:
    op.drop_column("alerts", "severity", schema="monitor")

    op.drop_column("settings", "cooldown_wall_break", schema="monitor")
    op.drop_column("settings", "cooldown_macro", schema="monitor")
    op.drop_column("settings", "risk_off_count_threshold", schema="monitor")
    op.drop_column("settings", "sensex_move_threshold", schema="monitor")
    op.drop_column("settings", "nifty_move_threshold", schema="monitor")
    op.drop_column("settings", "gold_move_threshold", schema="monitor")
    op.drop_column("settings", "crude_move_threshold", schema="monitor")

    op.drop_column("session_state", "last_sensex_spot", schema="monitor")
    op.drop_column("session_state", "last_nifty_spot", schema="monitor")
    op.drop_column("session_state", "open_sensex", schema="monitor")
    op.drop_column("session_state", "open_nifty", schema="monitor")
    op.drop_column("session_state", "open_gold", schema="monitor")
    op.drop_column("session_state", "open_crude", schema="monitor")

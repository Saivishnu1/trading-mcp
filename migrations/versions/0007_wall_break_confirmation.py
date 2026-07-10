"""Priority 1 (2026-07-10) — wall-break hold-confirmation streaks and the
new oi_wall_rejection alert's confirm-candles threshold.

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-10 00:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("session_state", sa.Column("call_wall_break_streak", sa.Integer(), server_default=sa.text("0")), schema="monitor")
    op.add_column("session_state", sa.Column("put_wall_break_streak", sa.Integer(), server_default=sa.text("0")), schema="monitor")
    op.add_column("session_state", sa.Column("call_wall_break_confirmed", sa.Boolean(), server_default=sa.text("false")), schema="monitor")
    op.add_column("session_state", sa.Column("put_wall_break_confirmed", sa.Boolean(), server_default=sa.text("false")), schema="monitor")

    op.add_column("settings", sa.Column("wall_break_confirm_candles", sa.Integer(), server_default=sa.text("3")), schema="monitor")


def downgrade() -> None:
    op.drop_column("settings", "wall_break_confirm_candles", schema="monitor")

    op.drop_column("session_state", "put_wall_break_confirmed", schema="monitor")
    op.drop_column("session_state", "call_wall_break_confirmed", schema="monitor")
    op.drop_column("session_state", "put_wall_break_streak", schema="monitor")
    op.drop_column("session_state", "call_wall_break_streak", schema="monitor")

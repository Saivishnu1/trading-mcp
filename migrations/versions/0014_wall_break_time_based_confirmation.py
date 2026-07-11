"""Piece C (2026-07-11) — time-based wall-hold confirmation, replacing the
poll-count-based streak (wall_break_confirm_candles /
call_wall_break_streak / put_wall_break_streak), which stopped meaning a
fixed duration once wall-hold is checked on live WS ticks instead of only
once per poll. The old columns are left in place, unused by new code, so
this migration is purely additive.

Revision ID: 0014
Revises: 0013
Create Date: 2026-07-11 00:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "settings",
        sa.Column("wall_break_confirm_seconds", sa.Integer(), server_default=sa.text("60")),
        schema="monitor",
    )
    op.add_column("session_state", sa.Column("call_wall_hold_since", sa.Text()), schema="monitor")
    op.add_column("session_state", sa.Column("put_wall_hold_since", sa.Text()), schema="monitor")


def downgrade() -> None:
    op.drop_column("session_state", "put_wall_hold_since", schema="monitor")
    op.drop_column("session_state", "call_wall_hold_since", schema="monitor")
    op.drop_column("settings", "wall_break_confirm_seconds", schema="monitor")

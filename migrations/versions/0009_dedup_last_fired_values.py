"""Priority B3 (2026-07-11) — near-duplicate re-fire guard for pcr_shift and
the hold-confirmed wall-break alerts: track the value actually FIRED, distinct
from the session-open reference the underlying threshold check compares
against.

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-11 00:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("session_state", sa.Column("last_fired_pcr", sa.Float()), schema="monitor")
    op.add_column("session_state", sa.Column("last_fired_call_wall_break_spot", sa.Float()), schema="monitor")
    op.add_column("session_state", sa.Column("last_fired_put_wall_break_spot", sa.Float()), schema="monitor")


def downgrade() -> None:
    op.drop_column("session_state", "last_fired_put_wall_break_spot", schema="monitor")
    op.drop_column("session_state", "last_fired_call_wall_break_spot", schema="monitor")
    op.drop_column("session_state", "last_fired_pcr", schema="monitor")

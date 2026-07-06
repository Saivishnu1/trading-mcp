"""Add last_morning_brief/last_eod_summary to monitor.session_state.

A systemd restart previously reset the in-memory "already sent today"
tracking in MarketMonitor.run(), causing the morning brief and EOD summary
to re-send on every restart. Persisting the last-sent date fixes this.

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-07 00:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("session_state", sa.Column("last_morning_brief", sa.Text()), schema="monitor")
    op.add_column("session_state", sa.Column("last_eod_summary", sa.Text()), schema="monitor")


def downgrade() -> None:
    op.drop_column("session_state", "last_eod_summary", schema="monitor")
    op.drop_column("session_state", "last_morning_brief", schema="monitor")

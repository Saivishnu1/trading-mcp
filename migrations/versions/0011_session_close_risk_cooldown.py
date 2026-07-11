"""Priority B7 (2026-07-11) — cooldown for the MCX session-close risk alert.

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-11 00:00:02.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("settings", sa.Column("cooldown_session_close_risk", sa.Integer(), server_default=sa.text("3600")), schema="monitor")


def downgrade() -> None:
    op.drop_column("settings", "cooldown_session_close_risk", schema="monitor")

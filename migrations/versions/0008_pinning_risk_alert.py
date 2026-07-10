"""Priority 3 (2026-07-10) — max-pain pinning-risk alert threshold and
cooldown for the monitor's proactive intraday check.

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-10 00:00:01.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("settings", sa.Column("pinning_risk_threshold_pct", sa.Float(), server_default=sa.text("0.5")), schema="monitor")
    op.add_column("settings", sa.Column("cooldown_pinning", sa.Integer(), server_default=sa.text("1800")), schema="monitor")


def downgrade() -> None:
    op.drop_column("settings", "cooldown_pinning", schema="monitor")
    op.drop_column("settings", "pinning_risk_threshold_pct", schema="monitor")

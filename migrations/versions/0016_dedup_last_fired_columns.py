"""Alert dedup tightening (2026-07-13) — MACRO_CRUDE and PINNING_RISK had no
dedup_key at all (only the coarser cooldown gate), and PCR_SHIFT's dedup
used OR semantics where pure time-passing alone could re-fire it with no
value change. Confirmed live: PINNING_RISK fired 3x in ~65 min, MACRO_CRUDE
3x in ~61 min, both with no meaningful underlying change. New columns store
the last-actually-FIRED value for each, mirroring the existing
last_fired_pcr/last_fired_*_wall_break_spot columns. Purely additive.

Revision ID: 0016
Revises: 0015
Create Date: 2026-07-13 00:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("session_state", sa.Column("last_fired_crude_pct", sa.Float()), schema="monitor")
    op.add_column("session_state", sa.Column("last_fired_pinning_distance", sa.Float()), schema="monitor")
    op.add_column("session_state", sa.Column("last_fired_pinning_max_pain", sa.Float()), schema="monitor")


def downgrade() -> None:
    op.drop_column("session_state", "last_fired_pinning_max_pain", schema="monitor")
    op.drop_column("session_state", "last_fired_pinning_distance", schema="monitor")
    op.drop_column("session_state", "last_fired_crude_pct", schema="monitor")

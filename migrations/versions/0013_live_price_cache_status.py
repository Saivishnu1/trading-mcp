"""Piece B diagnostic (2026-07-11) — persist whether the last
check_market_conditions poll's NIFTY/SENSEX spot came from LivePriceCache
(the WS feed) or the REST option-chain fallback, so get_monitor_status() can
answer that without SSHing into the Oracle VM or grepping logs.

Revision ID: 0013
Revises: 0012
Create Date: 2026-07-11 00:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("session_state", sa.Column("live_price_nifty_ltp", sa.Float()), schema="monitor")
    op.add_column(
        "session_state",
        sa.Column("live_price_nifty_cache_hit", sa.Boolean(), server_default=sa.text("false")),
        schema="monitor",
    )
    op.add_column("session_state", sa.Column("live_price_sensex_ltp", sa.Float()), schema="monitor")
    op.add_column(
        "session_state",
        sa.Column("live_price_sensex_cache_hit", sa.Boolean(), server_default=sa.text("false")),
        schema="monitor",
    )
    op.add_column("session_state", sa.Column("live_price_checked_at", sa.Text()), schema="monitor")


def downgrade() -> None:
    op.drop_column("session_state", "live_price_checked_at", schema="monitor")
    op.drop_column("session_state", "live_price_sensex_cache_hit", schema="monitor")
    op.drop_column("session_state", "live_price_sensex_ltp", schema="monitor")
    op.drop_column("session_state", "live_price_nifty_cache_hit", schema="monitor")
    op.drop_column("session_state", "live_price_nifty_ltp", schema="monitor")

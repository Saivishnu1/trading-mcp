"""SL/target/trailing-SL columns on zerodha.orders (2026-07-12).

Lets the positions page show "this position has an active SL @ X / target @
Y" and identify which past order to modify, instead of only knowing an order
was placed. active tracks whether this order's SL/target leg is still live
(cleared on modify-to-cancelled, sell-to-close, or a confirmed fill/rejection
via the order-update listener) — see src/execution/repository.py.

Revision ID: 0015
Revises: 0014
Create Date: 2026-07-12 00:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("sl_trigger_price", sa.Float()), schema="zerodha")
    op.add_column("orders", sa.Column("sl_limit_price", sa.Float()), schema="zerodha")
    op.add_column("orders", sa.Column("tgt_trigger_price", sa.Float()), schema="zerodha")
    op.add_column("orders", sa.Column("tgt_limit_price", sa.Float()), schema="zerodha")
    op.add_column("orders", sa.Column("trailing_sl_points", sa.Float()), schema="zerodha")
    op.add_column(
        "orders",
        sa.Column("sl_target_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        schema="zerodha",
    )


def downgrade() -> None:
    op.drop_column("orders", "sl_target_active", schema="zerodha")
    op.drop_column("orders", "trailing_sl_points", schema="zerodha")
    op.drop_column("orders", "tgt_limit_price", schema="zerodha")
    op.drop_column("orders", "tgt_trigger_price", schema="zerodha")
    op.drop_column("orders", "sl_limit_price", schema="zerodha")
    op.drop_column("orders", "sl_trigger_price", schema="zerodha")

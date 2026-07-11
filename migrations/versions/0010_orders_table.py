"""Order-placement audit log (2026-07-11) — zerodha.orders.

Append-only record of every order submitted via the Telegram bot or the web
app. Requested fields are the immutable entry-time intent; broker_order_id /
status / raw_response capture the broker response at submission time.

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-11 00:00:01.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "orders",
        sa.Column("id",               sa.Text(),    primary_key=True, nullable=False),
        sa.Column("user_id",          sa.Text()),
        sa.Column("broker",           sa.Text(),    nullable=False),
        sa.Column("source",           sa.Text(),    nullable=False),
        sa.Column("symbol",           sa.Text()),
        sa.Column("security_id",      sa.Text(),    nullable=False),
        sa.Column("exchange",         sa.Text(),    nullable=False),
        sa.Column("segment",          sa.Text()),
        sa.Column("transaction_type", sa.Text(),    nullable=False),
        sa.Column("quantity",         sa.Integer(), nullable=False),
        sa.Column("order_type",       sa.Text(),    nullable=False),
        sa.Column("product",          sa.Text()),
        sa.Column("limit_price",      sa.Float()),
        sa.Column("broker_order_id",  sa.Text()),
        sa.Column("status",           sa.Text(),    nullable=False),
        sa.Column("order_status",     sa.Text()),
        sa.Column("raw_response",     sa.Text()),
        sa.Column("created_at",       sa.Text(),    nullable=False),
        sa.CheckConstraint("transaction_type IN ('BUY','SELL')", name="valid_txn_type"),
        sa.CheckConstraint("source IN ('telegram','web','mcp')", name="valid_order_source"),
        schema="zerodha",
    )
    op.create_index("ix_orders_user_id",    "orders", ["user_id"],    schema="zerodha")
    op.create_index("ix_orders_created_at", "orders", ["created_at"], schema="zerodha")
    op.create_index("ix_orders_symbol",     "orders", ["symbol"],     schema="zerodha")


def downgrade() -> None:
    op.drop_index("ix_orders_symbol",     table_name="orders", schema="zerodha")
    op.drop_index("ix_orders_created_at", table_name="orders", schema="zerodha")
    op.drop_index("ix_orders_user_id",    table_name="orders", schema="zerodha")
    op.drop_table("orders", schema="zerodha")

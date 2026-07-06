"""Add optional Telegram delivery channel to monitor.users.

Telegram Bot API has no onboarding handshake delay (unlike CallMeBot's
WhatsApp opt-in), so it's a useful fallback channel while/if CallMeBot is
slow or down. Both columns are nullable — CallMeBot remains the only
required channel; alerts.py fans out to whichever is configured.

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-06 00:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("telegram_bot_token", sa.Text()), schema="monitor")
    op.add_column("users", sa.Column("telegram_chat_id", sa.Text()), schema="monitor")


def downgrade() -> None:
    op.drop_column("users", "telegram_chat_id", schema="monitor")
    op.drop_column("users", "telegram_bot_token", schema="monitor")

"""First-run bootstrap for the monitor schema — creates the single default user
from env vars if monitor.users is empty. Multi-tenant schema, single user today.
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone

from src.db.config import get_session

logger = logging.getLogger(__name__)


class MonitorBootstrap:

    async def ensure_default_user(self) -> dict:
        from sqlalchemy import select

        from src.db.models import MonitorUser

        async with get_session() as session:
            result = await session.execute(select(MonitorUser))
            existing = result.scalars().first()
            if existing is not None:
                logger.info("Existing user loaded: %s", existing.name)
                return {c.name: getattr(existing, c.name) for c in existing.__table__.columns}

            name = os.environ.get("DEFAULT_USER_NAME", "").strip()
            phone = os.environ.get("DEFAULT_WHATSAPP_PHONE", "").strip()
            key = os.environ.get("DEFAULT_CALLMEBOT_API_KEY", "").strip()
            # Optional second channel — Telegram has no onboarding delay,
            # unlike CallMeBot's WhatsApp opt-in handshake.
            telegram_bot_token = os.environ.get("DEFAULT_TELEGRAM_BOT_TOKEN", "").strip() or None
            telegram_chat_id = os.environ.get("DEFAULT_TELEGRAM_CHAT_ID", "").strip() or None

            has_callmebot = bool(phone and key)
            has_telegram = bool(telegram_bot_token and telegram_chat_id)
            if not name or not (has_callmebot or has_telegram):
                raise RuntimeError(
                    "No monitor.users row exists and DEFAULT_USER_NAME plus at least one "
                    "alert channel (DEFAULT_WHATSAPP_PHONE + DEFAULT_CALLMEBOT_API_KEY, or "
                    "DEFAULT_TELEGRAM_BOT_TOKEN + DEFAULT_TELEGRAM_CHAT_ID) are not all set."
                )

            now = datetime.now(timezone.utc).isoformat()
            user = MonitorUser(
                id=str(uuid.uuid4()),
                name=name,
                whatsapp_phone=phone,
                callmebot_key=key,
                telegram_bot_token=telegram_bot_token,
                telegram_chat_id=telegram_chat_id,
                broker_type="zerodha+indmoney",
                is_default=True,
                is_active=True,
                created_at=now,
                updated_at=now,
            )
            session.add(user)
            await session.flush()
            await self._ensure_default_settings(session, user.id)
            logger.info("Default user created: %s", name)
            return {c.name: getattr(user, c.name) for c in user.__table__.columns}

    async def _ensure_default_settings(self, session, user_id: str) -> None:
        from sqlalchemy import select

        from src.db.models import MonitorSettings

        result = await session.execute(
            select(MonitorSettings).where(MonitorSettings.user_id == user_id)
        )
        if result.scalar_one_or_none() is not None:
            return
        session.add(MonitorSettings(
            user_id=user_id,
            updated_at=datetime.now(timezone.utc).isoformat(),
        ))

    async def ensure_default_settings(self, user_id: str) -> None:
        async with get_session() as session:
            await self._ensure_default_settings(session, user_id)

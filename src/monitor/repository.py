"""Async repository for the monitor.* schema — thin wrapper over SQLAlchemy sessions.

All methods take/return plain dicts so the rest of src/monitor/ never touches
ORM row objects directly. Timestamps are stored as ISO-8601 strings, matching
the convention already used by src/db/models.py (Trade, RecommendationLog).

sqlalchemy and src.db.models are Linux-only in this repo (see src/db/config.py) —
src.db.models wraps every ORM class in try/except ImportError, so the names
simply don't exist on Windows dev. Every method below imports them lazily so
this module — and anything that imports it, e.g. scheduler.py — stays
importable on Windows for unrelated unit tests. Only the Oracle VM systemd
service actually calls these methods.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import pytz

from src.db.config import get_session

_IST = pytz.timezone("Asia/Kolkata")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_ist() -> str:
    """IST calendar date (YYYY-MM-DD). The Oracle VM runs in UTC, so
    _now()[:10] would be a day behind the real IST date during IST
    00:00-05:29 — session_date is an IST trading-session concept and must
    not silently fall back to the UTC date."""
    return datetime.now(_IST).date().isoformat()


def _row_to_dict(row: Any) -> dict:
    return {c.name: getattr(row, c.name) for c in row.__table__.columns}


class MonitorRepository:
    """Data access for the monitor schema. One instance is stateless/reusable."""

    async def get_active_users(self) -> list[dict]:
        from sqlalchemy import select
        from src.db.models import MonitorUser
        async with get_session() as session:
            result = await session.execute(
                select(MonitorUser).where(MonitorUser.is_active.is_(True))
            )
            return [_row_to_dict(r) for r in result.scalars().all()]

    async def get_user_settings(self, user_id: str) -> dict:
        from sqlalchemy import select
        from src.db.models import MonitorSettings
        async with get_session() as session:
            result = await session.execute(
                select(MonitorSettings).where(MonitorSettings.user_id == user_id)
            )
            row = result.scalar_one_or_none()
            return _row_to_dict(row) if row else {}

    async def get_active_positions(self, user_id: str) -> list[dict]:
        from sqlalchemy import select
        from src.db.models import MonitorPosition
        async with get_session() as session:
            result = await session.execute(
                select(MonitorPosition).where(
                    MonitorPosition.user_id == user_id,
                    MonitorPosition.status == "active",
                )
            )
            return [_row_to_dict(r) for r in result.scalars().all()]

    async def upsert_position(self, user_id: str, position: dict) -> dict:
        from sqlalchemy import select
        from src.db.models import MonitorPosition
        key = dict(
            user_id=user_id,
            broker=position["broker"],
            symbol=position["symbol"],
            expiry=position["expiry"],
            strike=position["strike"],
            option_type=position["option_type"],
        )
        async with get_session() as session:
            result = await session.execute(
                select(MonitorPosition).filter_by(**key)
            )
            row = result.scalar_one_or_none()
            now = _now()
            if row is None:
                row = MonitorPosition(
                    id=str(uuid.uuid4()),
                    exchange=position.get("exchange", "NSE"),
                    entry_premium=position["entry_premium"],
                    qty=position["qty"],
                    status="active",
                    created_at=now,
                    updated_at=now,
                    **key,
                )
                session.add(row)
            else:
                row.entry_premium = position.get("entry_premium", row.entry_premium)
                row.qty = position.get("qty", row.qty)
                row.status = "active"
                row.updated_at = now
            await session.flush()
            return _row_to_dict(row)

    async def close_position(self, user_id: str, position_id: str) -> None:
        from sqlalchemy import update
        from src.db.models import MonitorPosition
        async with get_session() as session:
            await session.execute(
                update(MonitorPosition)
                .where(MonitorPosition.id == position_id, MonitorPosition.user_id == user_id)
                .values(status="closed", updated_at=_now())
            )

    async def get_peak(self, position_id: str) -> dict | None:
        from sqlalchemy import select
        from src.db.models import MonitorPeak
        async with get_session() as session:
            result = await session.execute(
                select(MonitorPeak).where(MonitorPeak.position_id == position_id)
            )
            row = result.scalar_one_or_none()
            return _row_to_dict(row) if row else None

    async def upsert_peak(self, position_id: str, peak: dict) -> None:
        from sqlalchemy import select
        from src.db.models import MonitorPeak
        async with get_session() as session:
            result = await session.execute(
                select(MonitorPeak).where(MonitorPeak.position_id == position_id)
            )
            row = result.scalar_one_or_none()
            now = _now()
            if row is None:
                row = MonitorPeak(
                    id=str(uuid.uuid4()),
                    user_id=peak["user_id"],
                    position_id=position_id,
                    peak_premium=peak["peak_premium"],
                    peak_at=now,
                    trailing_sl=peak["trailing_sl"],
                    trailing_sl_pct=peak["trailing_sl_pct"],
                    updated_at=now,
                )
                session.add(row)
            else:
                row.peak_premium = peak["peak_premium"]
                row.peak_at = now
                row.trailing_sl = peak["trailing_sl"]
                row.trailing_sl_pct = peak["trailing_sl_pct"]
                row.updated_at = now

    async def save_alert(self, user_id: str, alert: dict) -> None:
        from src.db.models import MonitorAlert
        async with get_session() as session:
            session.add(MonitorAlert(
                id=str(uuid.uuid4()),
                user_id=user_id,
                alert_type=alert["alert_type"],
                symbol=alert.get("symbol"),
                message=alert["message"],
                delivered=alert.get("delivered", True),
                delivered_at=_now() if alert.get("delivered", True) else None,
                created_at=_now(),
                severity=alert.get("severity", "medium"),
            ))

    async def get_recent_alerts(self, user_id: str, hours: int = 24) -> list[dict]:
        from sqlalchemy import select
        from src.db.models import MonitorAlert
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        async with get_session() as session:
            result = await session.execute(
                select(MonitorAlert)
                .where(MonitorAlert.user_id == user_id, MonitorAlert.created_at >= cutoff)
                .order_by(MonitorAlert.created_at.desc())
            )
            return [_row_to_dict(r) for r in result.scalars().all()]

    async def get_last_alert_time(self, user_id: str, alert_type: str, symbol: str) -> datetime | None:
        from sqlalchemy import select
        from src.db.models import MonitorAlert
        async with get_session() as session:
            result = await session.execute(
                select(MonitorAlert)
                .where(
                    MonitorAlert.user_id == user_id,
                    MonitorAlert.alert_type == alert_type,
                    MonitorAlert.symbol == symbol,
                )
                .order_by(MonitorAlert.created_at.desc())
                .limit(1)
            )
            row = result.scalar_one_or_none()
            if row is None:
                return None
            return datetime.fromisoformat(row.created_at)

    async def get_session_state(self, user_id: str) -> dict | None:
        from sqlalchemy import select
        from src.db.models import MonitorSessionState
        async with get_session() as session:
            result = await session.execute(
                select(MonitorSessionState).where(MonitorSessionState.user_id == user_id)
            )
            row = result.scalar_one_or_none()
            return _row_to_dict(row) if row else None

    async def save_session_state(self, user_id: str, state: dict) -> None:
        from sqlalchemy import select
        from src.db.models import MonitorSessionState
        async with get_session() as session:
            result = await session.execute(
                select(MonitorSessionState).where(MonitorSessionState.user_id == user_id)
            )
            row = result.scalar_one_or_none()
            now = _now()
            if row is None:
                session.add(MonitorSessionState(
                    user_id=user_id,
                    open_pcr=state.get("open_pcr"),
                    open_vix=state.get("open_vix"),
                    open_call_wall=state.get("open_call_wall"),
                    open_put_wall=state.get("open_put_wall"),
                    open_crude=state.get("open_crude"),
                    open_gold=state.get("open_gold"),
                    open_nifty=state.get("open_nifty"),
                    open_sensex=state.get("open_sensex"),
                    last_nifty_spot=state.get("last_nifty_spot"),
                    last_sensex_spot=state.get("last_sensex_spot"),
                    session_date=state.get("session_date", _today_ist()),
                    last_morning_brief=state.get("last_morning_brief"),
                    last_eod_summary=state.get("last_eod_summary"),
                    updated_at=now,
                ))
            else:
                row.open_pcr = state.get("open_pcr", row.open_pcr)
                row.open_vix = state.get("open_vix", row.open_vix)
                row.open_call_wall = state.get("open_call_wall", row.open_call_wall)
                row.open_put_wall = state.get("open_put_wall", row.open_put_wall)
                row.open_crude = state.get("open_crude", row.open_crude)
                row.open_gold = state.get("open_gold", row.open_gold)
                row.open_nifty = state.get("open_nifty", row.open_nifty)
                row.open_sensex = state.get("open_sensex", row.open_sensex)
                row.last_nifty_spot = state.get("last_nifty_spot", row.last_nifty_spot)
                row.last_sensex_spot = state.get("last_sensex_spot", row.last_sensex_spot)
                row.session_date = state.get("session_date", row.session_date)
                row.last_morning_brief = state.get("last_morning_brief", row.last_morning_brief)
                row.last_eod_summary = state.get("last_eod_summary", row.last_eod_summary)
                row.updated_at = now

    async def save_heartbeat(self, user_id: str, field: str) -> None:
        """Stamp one of last_heartbeat / last_market_check / last_position_check /
        last_alert_sent with the current time, so get_monitor_status() can report
        liveness without SSHing into the Oracle VM."""
        if field not in ("last_heartbeat", "last_market_check", "last_position_check", "last_alert_sent"):
            raise ValueError(f"Unknown heartbeat field: {field}")
        from sqlalchemy import select
        from src.db.models import MonitorSessionState
        async with get_session() as session:
            result = await session.execute(
                select(MonitorSessionState).where(MonitorSessionState.user_id == user_id)
            )
            row = result.scalar_one_or_none()
            now = _now()
            if row is None:
                session.add(MonitorSessionState(
                    user_id=user_id,
                    session_date=_today_ist(),
                    updated_at=now,
                    **{field: now},
                ))
            else:
                setattr(row, field, now)
                row.updated_at = now

    async def get_cached_instrument(self, broker: str, instrument_id: str) -> dict | None:
        """Return the cached instrument, or None if missing or past expires_at."""
        from sqlalchemy import select
        from src.db.models import MonitorInstrumentCache
        async with get_session() as session:
            result = await session.execute(
                select(MonitorInstrumentCache).where(
                    MonitorInstrumentCache.broker == broker,
                    MonitorInstrumentCache.instrument_id == instrument_id,
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                return None
            if row.expires_at <= _now():
                return None
            return _row_to_dict(row)

    async def cache_instrument(
        self, broker: str, instrument_id: str, resolved: dict, ttl_hours: int = 24
    ) -> None:
        from sqlalchemy import select
        from src.db.models import MonitorInstrumentCache
        async with get_session() as session:
            result = await session.execute(
                select(MonitorInstrumentCache).where(
                    MonitorInstrumentCache.broker == broker,
                    MonitorInstrumentCache.instrument_id == instrument_id,
                )
            )
            row = result.scalar_one_or_none()
            now = _now()
            expires_at = (datetime.now(timezone.utc) + timedelta(hours=ttl_hours)).isoformat()
            if row is None:
                session.add(MonitorInstrumentCache(
                    broker=broker,
                    instrument_id=instrument_id,
                    symbol=resolved["symbol"],
                    expiry=resolved["expiry"],
                    strike=resolved["strike"],
                    option_type=resolved["option_type"],
                    exchange=resolved.get("exchange", "NSE"),
                    expires_at=expires_at,
                    updated_at=now,
                ))
            else:
                row.symbol = resolved["symbol"]
                row.expiry = resolved["expiry"]
                row.strike = resolved["strike"]
                row.option_type = resolved["option_type"]
                row.exchange = resolved.get("exchange", row.exchange)
                row.expires_at = expires_at
                row.updated_at = now

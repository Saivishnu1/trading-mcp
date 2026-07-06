"""Adaptive polling scheduler — runs the monitor loop for all active users."""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, time

import pytz

from src.monitor.alerts import WhatsAppAlerter
from src.monitor.bootstrap import MonitorBootstrap
from src.monitor.conditions import MarketConditions
from src.monitor.position_tracker import PositionTracker
from src.monitor.repository import MonitorRepository

logger = logging.getLogger(__name__)


class MarketMonitor:

    MARKET_OPEN = time(9, 15)
    MARKET_CLOSE = time(15, 30)
    MORNING_BRIEF_TIME = time(9, 20)
    EOD_SUMMARY_TIME = time(15, 35)
    IST = pytz.timezone("Asia/Kolkata")
    POSITION_SYNC_SECONDS = 1800
    # Slowest possible adaptive interval (see get_poll_interval) — used as the
    # staleness threshold since get_monitor_status() can't know which interval
    # was actually active on the last loop iteration.
    MAX_POLL_INTERVAL_SECONDS = 900
    STALE_AFTER_SECONDS = MAX_POLL_INTERVAL_SECONDS * 2

    def __init__(self):
        self.repo = MonitorRepository()
        self.bootstrap = MonitorBootstrap()
        self.tracker = PositionTracker(repo=self.repo)
        self.conditions = MarketConditions()
        self.alerter = WhatsAppAlerter()

    def get_poll_interval(self, min_dte: int, max_premium: float) -> int:
        if min_dte == 0:
            base = 60
        elif min_dte == 1:
            base = 120
        elif min_dte <= 3:
            base = 300
        else:
            base = 900

        if max_premium > 200:
            premium_interval = 60
        elif max_premium > 100:
            premium_interval = 120
        else:
            premium_interval = base

        return min(base, premium_interval)

    def is_market_open(self) -> bool:
        now = datetime.now(self.IST).time()
        return self.MARKET_OPEN <= now <= self.MARKET_CLOSE

    async def _get_vix(self) -> float:
        try:
            from src.market.service import MarketService
            svc = MarketService()
            data = svc.get_india_vix()
            return float(data.get("value", 0)) if isinstance(data, dict) else 0.0
        except Exception as exc:
            logger.debug("_get_vix error: %s", exc)
            return 0.0

    async def send_morning_brief(self, user: dict) -> None:
        positions = await self.repo.get_active_positions(user["id"])
        vix = await self._get_vix()
        data = {
            "date": date.today().isoformat(),
            "expiry": "",
            "nifty": 0,
            "sensex": 0,
            "vix": vix,
            "global_sentiment": "",
            "positions": positions,
            "support": "",
            "resistance": "",
        }
        await self.alerter.send_morning_brief(user, data)

    async def send_eod_summary(self, user: dict) -> None:
        positions = await self.repo.get_active_positions(user["id"])
        data = {
            "date": date.today().isoformat(),
            "nifty_close": 0,
            "nifty_change": 0.0,
            "sensex_close": 0,
            "sensex_change": 0.0,
            "realized_pnl": 0,
            "open_count": len(positions),
            "tomorrow_note": "",
        }
        await self.alerter.send_eod_summary(user, data)

    async def check_market_conditions(self, user: dict) -> None:
        settings = await self.repo.get_user_settings(user["id"])
        session_state = await self.repo.get_session_state(user["id"])
        if not session_state:
            return
        # PCR/VIX shift and wall-break checks reuse the same cooldown +
        # alert-persist pattern as PositionTracker._maybe_alert but at the
        # market level rather than per-position; left as an extension point
        # for src/options/analytics.py-backed live PCR/VIX values.

    async def run(self) -> None:
        await self.bootstrap.ensure_default_user()

        last_morning_brief: date | None = None
        last_eod_summary: date | None = None
        last_position_sync: datetime | None = None

        while True:
            now = datetime.now(self.IST)
            users = await self.repo.get_active_users()

            for user in users:
                await self.repo.save_heartbeat(user["id"], "last_heartbeat")

                if now.time() >= self.MORNING_BRIEF_TIME and last_morning_brief != now.date():
                    await self.send_morning_brief(user)
                    last_morning_brief = now.date()

                if now.time() >= self.EOD_SUMMARY_TIME and last_eod_summary != now.date():
                    await self.send_eod_summary(user)
                    last_eod_summary = now.date()

                if self.is_market_open():
                    if last_position_sync is None or (now - last_position_sync).total_seconds() >= self.POSITION_SYNC_SECONDS:
                        await self.tracker.sync_from_broker(user)
                        last_position_sync = now
                        await self.repo.save_heartbeat(user["id"], "last_position_check")

                    vix = await self._get_vix()
                    await self.tracker.check_positions(user, vix)
                    await self.check_market_conditions(user)
                    await self.repo.save_heartbeat(user["id"], "last_market_check")

            positions = await self.repo.get_active_positions(users[0]["id"]) if users else []
            min_dte = min((p.get("dte", 7) for p in positions), default=7)
            max_premium = max((p.get("current_premium", 0) for p in positions), default=0)
            interval = self.get_poll_interval(min_dte, max_premium)
            await asyncio.sleep(interval)

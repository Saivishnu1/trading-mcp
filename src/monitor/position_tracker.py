"""Syncs open option positions from the broker into monitor.positions and
checks each one against trailing-SL / profit-milestone conditions."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time

import pytz

from src.brokers.factory import get_broker_adapter
from src.brokers.indmoney import INDmoneyBroker
from src.monitor.alerts import WhatsAppAlerter
from src.monitor.conditions import MarketConditions
from src.monitor.position_price_feed import PositionPriceCache, get_position_instrument_resolver
from src.monitor.repository import MonitorRepository
from src.monitor.symbol_resolver import PositionSymbolResolver
from src.monitor.trailing_sl import TrailingSLCalculator

logger = logging.getLogger(__name__)

# The Oracle VM runs in UTC — date.today() would use the UTC date, which is
# a day behind the real IST calendar date during IST 00:00-05:29 (IST is
# UTC+5:30). DTE (days to expiry) must use the IST date, not the OS date,
# or a same-day-expiry position gets bucketed one DTE too high right when
# the tightest 0-DTE trailing-SL should apply.
_IST = pytz.timezone("Asia/Kolkata")

# Priority B7 (2026-07-11) — MCX closes at 23:30 IST, well past NSE's 15:30
# and past when attention typically shifts away. See
# MarketConditions.check_session_close_risk.
_MCX_CLOSE_TIME = time(23, 30)


def _raw_option_items(broker_name: str, raw: dict) -> list[dict]:
    """Extract the list of raw position rows that carry an option instrument id."""
    if broker_name == "zerodha":
        return raw.get("net", []) or []
    if broker_name == "indmoney":
        # INDmoneyBroker.get_raw_positions() wraps the parsed JSON one level
        # deeper under "body" (see INDmoneyBroker._raw_get) — the actual
        # positions payload is body.data.{net_positions,day_positions}.
        if not isinstance(raw, dict):
            return []
        body = raw.get("body", raw)
        data = body.get("data", body) if isinstance(body, dict) else {}
        if isinstance(data, dict):
            return (data.get("net_positions") or []) + (data.get("day_positions") or [])
        return []
    return []


def _instrument_id(broker_name: str, row: dict) -> str | None:
    if broker_name == "zerodha":
        return row.get("tradingsymbol")
    if broker_name == "indmoney":
        return row.get("security_id") or row.get("scrip_code")
    return None


class PositionTracker:

    def __init__(
        self,
        repo: MonitorRepository | None = None,
        resolver: PositionSymbolResolver | None = None,
        trailing_sl_calc: TrailingSLCalculator | None = None,
        alerter: WhatsAppAlerter | None = None,
        conditions: MarketConditions | None = None,
        price_cache: PositionPriceCache | None = None,
    ):
        self.repo = repo or MonitorRepository()
        self.resolver = resolver or PositionSymbolResolver(self.repo)
        self.trailing_sl = trailing_sl_calc or TrailingSLCalculator()
        self.alerter = alerter or WhatsAppAlerter()
        self.conditions = conditions or MarketConditions()
        self.instrument_resolver = get_position_instrument_resolver()
        # on_tick fires the SAME SL/profit-milestone evaluation used by the
        # poll loop the moment a price tick arrives for a subscribed
        # position, instead of waiting for the next check_positions() call
        # (which can be up to 900s away — see get_poll_interval). The poll
        # loop below still runs too, as a safety net: if the WS feed is
        # down/unresolvable for a position, it falls back to a corrected
        # REST quote on the same cadence as before this module existed.
        self.price_cache = price_cache or PositionPriceCache(on_tick=self._on_price_tick)
        # Context the tick callback needs (it only gets position_id + ltp),
        # refreshed every check_positions() call from the poll loop.
        self._position_context: dict[str, dict] = {}
        # Per-position locks so a WS tick and the poll loop can never
        # evaluate/upsert the same position's peak state concurrently.
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock_for(self, position_id: str) -> asyncio.Lock:
        lock = self._locks.get(position_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[position_id] = lock
        return lock

    async def sync_from_broker(self, user: dict) -> None:
        broker_names = [b.strip() for b in user["broker_type"].split("+") if b.strip()]
        seen_keys: set[tuple] = set()

        for broker_name in broker_names:
            try:
                adapter = get_broker_adapter(broker_name)
            except ValueError:
                continue
            get_raw = getattr(adapter, "get_raw_positions", None)
            if get_raw is None:
                continue
            raw = await get_raw()
            for row in _raw_option_items(broker_name, raw):
                iid = _instrument_id(broker_name, row)
                if not iid:
                    continue
                resolved = await self.resolver.resolve(broker_name, iid)
                if resolved is None:
                    continue

                qty = int(row.get("quantity") or row.get("net_quantity") or 0)
                if qty == 0:
                    continue
                entry_premium = float(row.get("average_price") or 0)

                position = {
                    "broker": broker_name,
                    "symbol": resolved["symbol"],
                    "expiry": resolved["expiry"],
                    "strike": resolved["strike"],
                    "option_type": resolved["option_type"],
                    "exchange": resolved.get("exchange", "NSE"),
                    "entry_premium": entry_premium,
                    "qty": qty,
                }
                saved = await self.repo.upsert_position(user["id"], position)
                seen_keys.add((broker_name, resolved["symbol"], resolved["expiry"], resolved["strike"], resolved["option_type"]))

        active = await self.repo.get_active_positions(user["id"])
        for pos in active:
            key = (pos["broker"], pos["symbol"], pos["expiry"], pos["strike"], pos["option_type"])
            if key not in seen_keys:
                await self.repo.close_position(user["id"], pos["id"])

    async def _get_current_premium(self, pos: dict) -> float | None:
        """Live WS cache first; REST quote (corrected instrument + scrip-code
        format — see position_price_feed.py's module docstring for the bug
        this replaces) only when the cache has no fresh value yet."""
        cached = self.price_cache.get(pos["id"])
        if cached is not None:
            return cached
        try:
            instrument = await self.instrument_resolver.resolve(
                symbol=pos["symbol"], expiry=pos["expiry"], strike=pos["strike"],
                option_type=pos["option_type"], exchange=pos.get("exchange", "NSE"),
            )
            if not instrument:
                return None
            segment, security_id = instrument.split(":", 1)
            # INDstocks REST quotes want "SEGMENT_TOKEN" (underscore); the WS
            # feed wants "SEGMENT:TOKEN" (colon) — same identifier, different
            # separator per endpoint (see live_price_feed.py's NSE:/NSE_ note).
            quotes = await INDmoneyBroker().get_quote([f"{segment}_{security_id}"])
            if quotes:
                return quotes[0].ltp
        except Exception as exc:
            logger.debug("_get_current_premium error for %s: %s", pos["symbol"], exc)
        return None

    async def check_positions(self, user: dict, vix: float) -> None:
        positions = await self.repo.get_active_positions(user["id"])
        settings = await self.repo.get_user_settings(user["id"])

        # Refresh tick-callback context BEFORE resubscribing, so a tick that
        # arrives mid-refresh always finds valid context for its position.
        active_ids = {pos["id"] for pos in positions}
        for pos in positions:
            self._position_context[pos["id"]] = {"user": user, "settings": settings, "vix": vix}
        for stale_id in [pid for pid in self._position_context if pid not in active_ids]:
            self._position_context.pop(stale_id, None)
            self._locks.pop(stale_id, None)

        try:
            await self.price_cache.refresh_subscriptions(positions)
        except Exception as exc:
            logger.warning("price_cache.refresh_subscriptions failed: %s", exc)

        for pos in positions:
            current_premium = await self._get_current_premium(pos)
            if current_premium is None:
                continue
            async with self._lock_for(pos["id"]):
                await self._evaluate_position(user, settings, pos, current_premium, vix)

    async def _on_price_tick(self, position_id: str, ltp: float) -> None:
        """Fired by PositionPriceCache the moment a subscribed position's
        price ticks — evaluates SL/profit-milestone immediately instead of
        waiting for the next poll (which can be up to 900s away)."""
        ctx = self._position_context.get(position_id)
        if ctx is None:
            return  # closed or not yet refreshed since subscribing
        positions = await self.repo.get_active_positions(ctx["user"]["id"])
        pos = next((p for p in positions if p["id"] == position_id), None)
        if pos is None:
            return
        async with self._lock_for(position_id):
            await self._evaluate_position(ctx["user"], ctx["settings"], pos, ltp, ctx["vix"])

    async def _evaluate_position(
        self, user: dict, settings: dict, pos: dict, current_premium: float, vix: float,
    ) -> None:
        if self.trailing_sl.should_stop_monitoring(current_premium, pos["entry_premium"]):
            return

        spot = pos.get("spot", 0.0)
        expiry_date = datetime.strptime(pos["expiry"], "%Y-%m-%d").date()
        dte = max((expiry_date - datetime.now(_IST).date()).days, 0)
        moneyness = self.trailing_sl.get_moneyness(spot, pos["strike"], pos["option_type"]) if spot else "ATM"

        peak = await self.repo.get_peak(pos["id"])
        if peak is None or current_premium > peak["peak_premium"]:
            trailing_sl_price = self.trailing_sl.get_trailing_sl_price(current_premium, dte, moneyness, vix)
            await self.repo.upsert_peak(pos["id"], {
                "user_id": user["id"],
                "peak_premium": current_premium,
                "trailing_sl": trailing_sl_price,
                "trailing_sl_pct": self.trailing_sl.calculate_pct(dte, moneyness, vix),
            })
            peak = {"peak_premium": current_premium, "trailing_sl": trailing_sl_price}

        triggered, reason = self.conditions.check_trailing_sl(current_premium, peak["trailing_sl"])
        if triggered:
            await self._maybe_alert(user, settings, pos, current_premium, spot, "trailing_sl", reason, "cooldown_trailing")

        triggered, reason = self.conditions.check_profit_milestone(
            pos["entry_premium"], current_premium, settings["profit_alert_pct"]
        )
        if triggered:
            await self._maybe_alert(user, settings, pos, current_premium, spot, "profit_milestone", reason, "cooldown_profit")

    async def _maybe_alert(self, user, settings, pos, current_premium, spot, alert_type, reason, cooldown_key) -> None:
        last_sent = await self.repo.get_last_alert_time(user["id"], alert_type, pos["symbol"])
        if self.conditions.is_alert_on_cooldown(last_sent, settings[cooldown_key]):
            return
        await self.alerter.send_position_alert(user, {
            **pos,
            "current_premium": current_premium,
            "pnl": (current_premium - pos["entry_premium"]) * pos["qty"],
            "spot": spot,
        }, reason)
        await self.repo.save_alert(user["id"], {
            "alert_type": alert_type,
            "symbol": pos["symbol"],
            "message": reason,
        })
        await self.repo.save_heartbeat(user["id"], "last_alert_sent")

"""Syncs open option positions from the broker into monitor.positions and
checks each one against trailing-SL / profit-milestone conditions."""
from __future__ import annotations

import logging
from datetime import datetime

import pytz

from src.brokers.factory import get_broker_adapter
from src.monitor.alerts import WhatsAppAlerter
from src.monitor.conditions import MarketConditions
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
    ):
        self.repo = repo or MonitorRepository()
        self.resolver = resolver or PositionSymbolResolver(self.repo)
        self.trailing_sl = trailing_sl_calc or TrailingSLCalculator()
        self.alerter = alerter or WhatsAppAlerter()
        self.conditions = conditions or MarketConditions()

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
        try:
            adapter = get_broker_adapter(pos["broker"])
            quotes = await adapter.get_quote([pos["symbol"]])
            if quotes:
                return quotes[0].ltp
        except Exception as exc:
            logger.debug("_get_current_premium error for %s: %s", pos["symbol"], exc)
        return None

    async def check_positions(self, user: dict, vix: float) -> None:
        positions = await self.repo.get_active_positions(user["id"])
        settings = await self.repo.get_user_settings(user["id"])

        for pos in positions:
            current_premium = await self._get_current_premium(pos)
            if current_premium is None:
                continue

            if self.trailing_sl.should_stop_monitoring(current_premium, pos["entry_premium"]):
                continue

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

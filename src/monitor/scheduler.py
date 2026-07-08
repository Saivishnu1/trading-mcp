"""Adaptive polling scheduler — runs the monitor loop for all active users."""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, time, timedelta

import pytz

from src.monitor.alerts import WhatsAppAlerter
from src.monitor.bootstrap import MonitorBootstrap
from src.monitor.conditions import MarketConditions
from src.monitor.market_intelligence import MarketIntelligence
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
        self.market_intelligence = MarketIntelligence(self.conditions)

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
            from src.intelligence.vix import get_india_vix
            loop = asyncio.get_running_loop()
            data = await loop.run_in_executor(None, get_india_vix)
            return float(data.get("level", 0)) if isinstance(data, dict) else 0.0
        except Exception as exc:
            logger.debug("_get_vix error: %s", exc)
            return 0.0

    # NSE (NIFTY) chain via get_options_service(), BSE (SENSEX) via
    # get_bse_options_service() — both singletons, same shape as the working
    # get_nifty_option_chain()/get_sensex_option_chain() MCP tools use
    # internally (src/tools/options.py's _fetch/_fetch_bse). This is the
    # live exchange-sourced spot ("underlyingValue" in the option chain
    # response), not yfinance — yfinance's ^BSESN quote lags/diverges from
    # the real BSE SENSEX print by a meaningful margin.
    _CHAIN_SOURCE = {
        "NIFTY": ("src.options.service", "get_options_service"),
        "SENSEX": ("src.options.bse_service", "get_bse_options_service"),
    }

    async def _get_option_chain(self, index: str) -> dict:
        module_name, getter_name = self._CHAIN_SOURCE[index]
        import importlib
        module = importlib.import_module(module_name)
        svc = getattr(module, getter_name)()
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, svc.get_option_chain, index)

    async def _get_index_quote(self, symbol: str) -> dict:
        """Return {"last_price", "previous_close"} for NIFTY/SENSEX.

        last_price comes from the option chain's underlyingValue — the same
        live exchange-sourced spot the confirmed-correct get_nifty_option_chain/
        get_sensex_option_chain MCP tools already return. previous_close still
        comes from MarketService (yfinance) since no option chain endpoint
        exposes a prior close; it's only used for the %change display, not
        the headline spot price."""
        last = 0.0
        try:
            chain = await self._get_option_chain(symbol)
            last = float(chain.get("records", {}).get("underlyingValue") or 0)
        except Exception as exc:
            logger.debug("_get_index_quote(%s) chain error: %s", symbol, exc)

        prev = 0.0
        try:
            from src.market.service import MarketService
            loop = asyncio.get_running_loop()
            quote = await loop.run_in_executor(None, MarketService().get_quote, symbol)
            prev = float(quote.get("previous_close") or 0)
            if not last:
                last = float(quote.get("last_price") or 0)
        except Exception as exc:
            logger.debug("_get_index_quote(%s) quote error: %s", symbol, exc)

        return {"last_price": last, "previous_close": prev}

    async def _get_key_levels(self) -> dict:
        """Support/resistance from NIFTY option chain OI. Returns
        {"support", "resistance"} — empty strings if the chain can't be fetched
        (public NSE endpoint, no auth, but can soft-block or time out)."""
        try:
            from src.options.analytics import identify_support_resistance_from_oi
            chain = await self._get_option_chain("NIFTY")
            levels = identify_support_resistance_from_oi(chain)
            nearest_support = levels.get("nearest_support") or {}
            nearest_resistance = levels.get("nearest_resistance") or {}
            return {
                "support": nearest_support.get("strike", ""),
                "resistance": nearest_resistance.get("strike", ""),
            }
        except Exception as exc:
            logger.debug("_get_key_levels error: %s", exc)
            return {"support": "", "resistance": ""}

    async def _get_calendar(self) -> dict:
        try:
            from src.market.calendar import get_market_calendar
            loop = asyncio.get_running_loop()
            cal = await loop.run_in_executor(None, get_market_calendar)
            return cal or {}
        except Exception as exc:
            logger.debug("_get_calendar error: %s", exc)
            return {}

    async def _get_global_sentiment(self) -> str:
        try:
            from src.intelligence.global_pulse import get_global_pulse
            loop = asyncio.get_running_loop()
            pulse = await loop.run_in_executor(None, get_global_pulse)
            return pulse.get("overall_sentiment", "") if isinstance(pulse, dict) else ""
        except Exception as exc:
            logger.debug("_get_global_sentiment error: %s", exc)
            return ""

    async def _get_global_pulse_raw(self) -> dict:
        try:
            from src.intelligence.global_pulse import get_global_pulse
            loop = asyncio.get_running_loop()
            pulse = await loop.run_in_executor(None, get_global_pulse)
            return pulse if isinstance(pulse, dict) and "error" not in pulse else {}
        except Exception as exc:
            logger.debug("_get_global_pulse_raw error: %s", exc)
            return {}

    def _macro_risk_note(self, global_pulse: dict, vix: float) -> str:
        """Plain-English macro observation for the morning brief — same
        risk-off signal count as MarketIntelligence.check_macro_signals,
        just formatted for a one-line brief instead of a standalone alert."""
        assets = global_pulse.get("assets") or {}
        crude = float((assets.get("crude_oil") or {}).get("change_pct") or 0)
        gold = float((assets.get("gold") or {}).get("change_pct") or 0)
        sp500 = float((assets.get("sp500") or {}).get("change_pct") or 0)

        signals = []
        if crude > 2:
            signals.append(f"Crude +{crude:.1f}%")
        if gold > 1.5:
            signals.append(f"Gold +{gold:.1f}%")
        if sp500 < -1:
            signals.append(f"S&P {sp500:.1f}%")
        if vix > 15:
            signals.append(f"VIX {vix:.1f}")

        if len(signals) >= 2:
            return f"RISK-OFF: {', '.join(signals)}"
        if len(signals) == 1:
            return f"Watch: {signals[0]}"
        return "Global: neutral"

    async def _get_realized_pnl_today(self) -> float:
        """Realized P&L from INDmoney's own funds snapshot (realized_pnl
        field) — no per-trade realized-P&L helper exists in this codebase
        (see INDmoneyBroker.get_funds), so this reads the broker's own
        aggregate rather than recomputing it from the trade book. The
        Fund dataclass doesn't expose this field, so get_raw_funds() is
        used and unwrapped the same way get_funds() does internally."""
        try:
            from src.brokers.indmoney import INDmoneyBroker
            raw = await INDmoneyBroker().get_raw_funds()
            body = raw.get("body") if isinstance(raw, dict) else None
            if not isinstance(body, dict):
                return 0.0
            data = body.get("data", body)
            return float(data.get("realized_pnl") or 0)
        except Exception as exc:
            logger.debug("_get_realized_pnl_today error: %s", exc)
            return 0.0

    def _today_ist(self) -> date:
        """IST calendar date. date.today() uses the OS/process local date,
        which is the UTC date on the Oracle VM. IST is UTC+5:30, so during
        IST 00:00-05:29 the UTC date is still "yesterday" — date.today()
        would be one day behind the real IST calendar date in that window."""
        return datetime.now(self.IST).date()

    def _tomorrow_note(self, calendar: dict) -> str:
        """Derive a plain observation from the calendar — next expiry and
        whether tomorrow is a trading holiday. No predictive language."""
        if not calendar:
            return ""
        next_expiry = calendar.get("next_nse_expiry", "")
        tomorrow = (self._today_ist() + timedelta(days=1)).isoformat()
        holidays = calendar.get("nse_holidays", [])
        if tomorrow in holidays:
            return f"Tomorrow is an NSE holiday. Next NIFTY expiry: {next_expiry}"
        if next_expiry:
            return f"Next NIFTY expiry: {next_expiry}"
        return ""

    async def send_morning_brief(self, user: dict) -> bool:
        from src.options.analytics import calculate_pcr

        positions = await self.repo.get_active_positions(user["id"])
        vix, nifty_q, sensex_q, key_levels, calendar, sentiment, global_pulse, nifty_chain = await asyncio.gather(
            self._get_vix(),
            self._get_index_quote("NIFTY"),
            self._get_index_quote("SENSEX"),
            self._get_key_levels(),
            self._get_calendar(),
            self._get_global_sentiment(),
            self._get_global_pulse_raw(),
            self._get_option_chain("NIFTY"),
        )
        data = {
            "date": self._today_ist().isoformat(),
            "expiry": calendar.get("next_nse_expiry", ""),
            "nifty": nifty_q["last_price"],
            "sensex": sensex_q["last_price"],
            "vix": vix,
            "global_sentiment": sentiment,
            "macro_note": self._macro_risk_note(global_pulse, vix),
            "positions": positions,
            "support": key_levels["support"],
            "resistance": key_levels["resistance"],
        }

        # Seed session-open reference values used by check_market_conditions'
        # PCR-shift/VIX-spike/wall-break checks — these columns previously
        # existed but were never written, so those checks could never fire.
        try:
            records = nifty_chain.get("records", {}) or {}
            expiry = (records.get("expiryDates") or [None])[0]
            pcr = calculate_pcr(nifty_chain, expiry)
            resistance_strike = key_levels.get("resistance")
            support_strike = key_levels.get("support")
            assets = global_pulse.get("assets") or {}
            await self.repo.save_session_state(user["id"], {
                "open_pcr": pcr.get("pcr_oi"),
                "open_vix": vix or None,
                "open_call_wall": resistance_strike or None,
                "open_put_wall": support_strike or None,
                "open_crude": (assets.get("crude_oil") or {}).get("change_pct"),
                "open_gold": (assets.get("gold") or {}).get("change_pct"),
                "open_nifty": nifty_q["last_price"] or None,
                "open_sensex": sensex_q["last_price"] or None,
                "last_nifty_spot": nifty_q["last_price"] or None,
                "last_sensex_spot": sensex_q["last_price"] or None,
            })
        except Exception as exc:
            logger.debug("send_morning_brief session-open seed failed: %s", exc)

        return await self.alerter.send_morning_brief(user, data)

    async def send_eod_summary(self, user: dict) -> bool:
        positions = await self.repo.get_active_positions(user["id"])
        nifty_q, sensex_q, calendar, realized_pnl = await asyncio.gather(
            self._get_index_quote("NIFTY"),
            self._get_index_quote("SENSEX"),
            self._get_calendar(),
            self._get_realized_pnl_today(),
        )

        def _pct_change(q: dict) -> float:
            if not q["previous_close"]:
                return 0.0
            return round((q["last_price"] - q["previous_close"]) / q["previous_close"] * 100, 2)

        data = {
            "date": self._today_ist().isoformat(),
            "nifty_close": nifty_q["last_price"],
            "nifty_change": _pct_change(nifty_q),
            "sensex_close": sensex_q["last_price"],
            "sensex_change": _pct_change(sensex_q),
            "realized_pnl": realized_pnl,
            "open_count": len(positions),
            "tomorrow_note": self._tomorrow_note(calendar),
        }
        return await self.alerter.send_eod_summary(user, data)

    async def _get_market_intelligence_data(self) -> dict:
        """Fetch everything MarketIntelligence.run_all_checks needs. Every
        sub-fetch is independently guarded — a single failing source (e.g.
        NSE option chain soft-blocked) must not prevent the other checks
        (macro, VIX) from running."""
        from src.options.analytics import calculate_pcr, identify_support_resistance_from_oi

        async def _nifty_chain_data() -> dict:
            try:
                chain = await self._get_option_chain("NIFTY")
                records = chain.get("records", {}) or {}
                spot = float(records.get("underlyingValue") or 0)
                expiry = (records.get("expiryDates") or [None])[0]
                pcr = calculate_pcr(chain, expiry)
                levels = identify_support_resistance_from_oi(chain, expiry)
                nearest_support = levels.get("nearest_support") or {}
                nearest_resistance = levels.get("nearest_resistance") or {}
                return {
                    "nifty_spot": spot,
                    "nifty_pcr": pcr.get("pcr_oi"),
                    "nifty_call_wall": nearest_resistance.get("strike"),
                    "nifty_put_wall": nearest_support.get("strike"),
                }
            except Exception as exc:
                logger.debug("_get_market_intelligence_data nifty chain error: %s", exc)
                return {}

        async def _sensex_spot() -> dict:
            try:
                chain = await self._get_option_chain("SENSEX")
                spot = float(chain.get("records", {}).get("underlyingValue") or 0)
                return {"sensex_spot": spot}
            except Exception as exc:
                logger.debug("_get_market_intelligence_data sensex chain error: %s", exc)
                return {}

        async def _global_pulse() -> dict:
            try:
                from src.intelligence.global_pulse import get_global_pulse
                loop = asyncio.get_running_loop()
                return {"global_pulse": await loop.run_in_executor(None, get_global_pulse)}
            except Exception as exc:
                logger.debug("_get_market_intelligence_data global_pulse error: %s", exc)
                return {}

        nifty_data, sensex_data, pulse_data, vix = await asyncio.gather(
            _nifty_chain_data(), _sensex_spot(), _global_pulse(), self._get_vix(),
        )
        return {**nifty_data, **sensex_data, **pulse_data, "vix": vix}

    async def check_market_conditions(self, user: dict) -> None:
        settings = await self.repo.get_user_settings(user["id"])
        session_state = await self.repo.get_session_state(user["id"])
        if not session_state:
            return

        market_data = await self._get_market_intelligence_data()
        alerts = await self.market_intelligence.run_all_checks(market_data, session_state, settings)

        for alert in alerts:
            cooldown_seconds = settings.get(alert["cooldown_key"], 1800)
            last_sent = await self.repo.get_last_alert_time(user["id"], alert["type"], alert["symbol"])
            if self.conditions.is_alert_on_cooldown(last_sent, cooldown_seconds):
                continue

            delivered = await self.alerter.send_macro_alert(user, alert["type"], alert["message"])
            await self.repo.save_alert(user["id"], {
                "alert_type": alert["type"],
                "symbol": alert["symbol"],
                "message": alert["message"],
                "severity": alert["severity"],
                "delivered": delivered,
            })
            await self.repo.save_heartbeat(user["id"], "last_alert_sent")

        # Persist the latest spot/PCR/VIX as the reference point for the NEXT
        # check_market_conditions call (index-move and wall-break diff
        # against the prior poll, not the session open — matches the
        # existing prev_spot convention in check_wall_break).
        await self.repo.save_session_state(user["id"], {
            "last_nifty_spot": market_data.get("nifty_spot") or session_state.get("last_nifty_spot"),
            "last_sensex_spot": market_data.get("sensex_spot") or session_state.get("last_sensex_spot"),
        })

    async def run(self) -> None:
        await self.bootstrap.ensure_default_user()

        last_position_sync: datetime | None = None

        while True:
            now = datetime.now(self.IST)
            today_str = now.date().isoformat()
            users = await self.repo.get_active_users()

            for user in users:
                await self.repo.save_heartbeat(user["id"], "last_heartbeat")
                session_state = await self.repo.get_session_state(user["id"]) or {}

                if (
                    now.time() >= self.MORNING_BRIEF_TIME
                    and session_state.get("last_morning_brief") != today_str
                ):
                    await self.send_morning_brief(user)
                    await self.repo.save_session_state(user["id"], {"last_morning_brief": today_str})

                if (
                    now.time() >= self.EOD_SUMMARY_TIME
                    and session_state.get("last_eod_summary") != today_str
                ):
                    await self.send_eod_summary(user)
                    await self.repo.save_session_state(user["id"], {"last_eod_summary": today_str})

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

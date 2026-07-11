"""Adaptive polling scheduler — runs the monitor loop for all active users."""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, time, timedelta, timezone

import pytz

from src.monitor.alerts import WhatsAppAlerter
from src.monitor.bootstrap import MonitorBootstrap
from src.monitor.conditions import MarketConditions
from src.monitor.live_price_feed import LivePriceCache
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
    MAX_POLL_INTERVAL_SECONDS = 300
    STALE_AFTER_SECONDS = MAX_POLL_INTERVAL_SECONDS * 2

    def __init__(self):
        self.repo = MonitorRepository()
        self.bootstrap = MonitorBootstrap()
        self.tracker = PositionTracker(repo=self.repo)
        self.conditions = MarketConditions()
        self.alerter = WhatsAppAlerter()
        self.market_intelligence = MarketIntelligence(self.conditions)
        self.live_prices = LivePriceCache(on_tick=self._on_index_tick)
        # Context _on_index_tick needs (it only gets symbol + ltp), refreshed
        # every check_market_conditions() call from the poll loop. Empty
        # until the first poll — a tick arriving before that is a no-op.
        self._market_context: dict = {}
        # Per-symbol locks so overlapping ticks for the same index can never
        # race on session_state's read-modify-write (NIFTY and SENSEX write
        # disjoint fields, so they don't need to share a lock).
        self._index_tick_locks: dict[str, asyncio.Lock] = {}

    def _index_lock(self, symbol: str) -> asyncio.Lock:
        lock = self._index_tick_locks.get(symbol)
        if lock is None:
            lock = asyncio.Lock()
            self._index_tick_locks[symbol] = lock
        return lock

    def get_poll_interval(self, min_dte: int, max_premium: float) -> int:
        # Piece C (2026-07-11) — the far-DTE tier was 900s (15 min), a real
        # detection-delay risk for market-condition checks (wall-break/PCR/
        # macro) since those still only run once per tick (position-level
        # SL/profit checks no longer wait on this loop at all — see
        # PositionPriceCache's on_tick in position_tracker.py). Lowered to
        # 300s: a meaningful cut to worst-case staleness without tripling+
        # the NSE/BSE option-chain REST call rate the way dropping to 60s
        # everywhere would.
        if min_dte == 0:
            base = 60
        elif min_dte == 1:
            base = 120
        else:
            base = 300

        if max_premium > 200:
            premium_interval = 60
        elif max_premium > 100:
            premium_interval = 120
        else:
            premium_interval = base

        return min(base, premium_interval)

    # Priority B7 (2026-07-11) — MCX trades until 23:30 IST, past NSE's
    # 15:30 close and past is_market_open()'s window, which is exactly why
    # a commodity position could sit open and unprotected with the main
    # loop already idle. check_mcx_session_close_risk runs independently of
    # is_market_open() so it still fires in that gap.
    MCX_CLOSE = time(23, 30)

    def is_market_open(self) -> bool:
        now = datetime.now(self.IST).time()
        return self.MARKET_OPEN <= now <= self.MARKET_CLOSE

    def is_mcx_session_active(self) -> bool:
        now = datetime.now(self.IST).time()
        return self.MARKET_OPEN <= now <= self.MCX_CLOSE

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
        from src.options.analytics import calculate_max_pain, calculate_pcr, identify_support_resistance_from_oi

        async def _nifty_chain_data() -> dict:
            try:
                chain = await self._get_option_chain("NIFTY")
                records = chain.get("records", {}) or {}
                # Piece B (2026-07-11) — spot from the live WS cache when
                # available (fresher than this poll's own REST snapshot could
                # ever be, and immune to NSE's occasional soft-block on the
                # option-chain endpoint); the chain's own underlyingValue is
                # the REST fallback, same as before this cache existed. PCR/
                # walls/max-pain below still need the full chain — there is
                # no WS feed for OI, only LTP.
                rest_spot = float(records.get("underlyingValue") or 0)
                cached_spot = self.live_prices.get("NIFTY")
                spot = cached_spot or rest_spot
                expiry = (records.get("expiryDates") or [None])[0]
                pcr = calculate_pcr(chain, expiry)
                levels = identify_support_resistance_from_oi(chain, expiry)
                nearest_support = levels.get("nearest_support") or {}
                nearest_resistance = levels.get("nearest_resistance") or {}

                # Priority 3 (2026-07-10) — max pain + expiry-week from the
                # same chain fetch, no extra I/O, for the pinning-risk check.
                mp = calculate_max_pain(chain, expiry)
                is_expiry_week = False
                if expiry:
                    try:
                        exp_date = datetime.strptime(expiry, "%d-%b-%Y").date()
                        is_expiry_week = (exp_date - self._today_ist()).days <= 5
                    except ValueError:
                        pass

                return {
                    "nifty_spot": spot,
                    "nifty_spot_cache_hit": cached_spot is not None,
                    "nifty_pcr": pcr.get("pcr_oi"),
                    "nifty_call_wall": nearest_resistance.get("strike"),
                    "nifty_put_wall": nearest_support.get("strike"),
                    "nifty_max_pain": mp.get("max_pain"),
                    "nifty_is_expiry_week": is_expiry_week,
                }
            except Exception as exc:
                logger.debug("_get_market_intelligence_data nifty chain error: %s", exc)
                return {}

        async def _sensex_spot() -> dict:
            try:
                chain = await self._get_option_chain("SENSEX")
                rest_spot = float(chain.get("records", {}).get("underlyingValue") or 0)
                cached_spot = self.live_prices.get("SENSEX")
                spot = cached_spot or rest_spot
                return {"sensex_spot": spot, "sensex_spot_cache_hit": cached_spot is not None}
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

    async def _process_alerts(
        self, user: dict, settings: dict, session_state: dict, alerts: list[dict],
    ) -> dict:
        """Cooldown-gate, dedup-gate, send, and persist a list of alert
        dicts. Returns dedup_updates (last-FIRED values to persist for
        near-duplicate re-fire gating). Shared by the poll path
        (check_market_conditions) and the tick-driven fast path
        (_on_index_tick) so both follow identical rules — see
        Priority B3 (2026-07-11) for why cooldown alone isn't enough."""
        dedup_updates: dict = {}
        for alert in alerts:
            # Raw wall-touch events (Priority 1, 2026-07-10) are logged for
            # backtesting/analysis but never pushed to Telegram — they carry
            # delivered=False explicitly and skip cooldown/alerter entirely.
            if alert.get("delivered") is False:
                await self.repo.save_alert(user["id"], {
                    "alert_type": alert["type"],
                    "symbol": alert["symbol"],
                    "message": alert["message"],
                    "severity": alert["severity"],
                    "delivered": False,
                })
                continue

            cooldown_seconds = settings.get(alert["cooldown_key"], 1800)
            last_sent = await self.repo.get_last_alert_time(user["id"], alert["type"], alert["symbol"])
            if self.conditions.is_alert_on_cooldown(last_sent, cooldown_seconds):
                continue

            # Priority B3 (2026-07-11) — near-duplicate re-fire guard beyond
            # the coarser cooldown above: only allow a re-fire if the value
            # has moved meaningfully from what was last actually FIRED (not
            # the session-open reference the underlying check compares
            # against), or enough time has passed regardless of delta.
            dedup_key = alert.get("dedup_key")
            if dedup_key is not None:
                last_fired_value = session_state.get(dedup_key)
                minutes_since_last_fire = (
                    (datetime.now(last_sent.tzinfo) - last_sent).total_seconds() / 60
                    if last_sent is not None else None
                )
                if not self.conditions.check_dedup_gate(
                    current_value=alert["value"],
                    last_fired_value=last_fired_value,
                    minutes_since_last_fire=minutes_since_last_fire,
                    min_delta=settings.get(f"{alert['type']}_dedup_min_delta", 0.05),
                    min_minutes=settings.get(f"{alert['type']}_dedup_min_minutes", 30),
                ):
                    continue
                dedup_updates[dedup_key] = alert["value"]

            delivered = await self.alerter.send_macro_alert(user, alert["type"], alert["message"])
            await self.repo.save_alert(user["id"], {
                "alert_type": alert["type"],
                "symbol": alert["symbol"],
                "message": alert["message"],
                "severity": alert["severity"],
                "delivered": delivered,
            })
            await self.repo.save_heartbeat(user["id"], "last_alert_sent")
        return dedup_updates

    async def check_market_conditions(self, user: dict) -> None:
        settings = await self.repo.get_user_settings(user["id"])
        session_state = await self.repo.get_session_state(user["id"])
        if not session_state:
            return

        # Piece C (2026-07-11) — primes _on_index_tick's context so a WS
        # tick arriving before the NEXT poll can still evaluate correctly.
        self._market_context = {"user": user, "settings": settings}

        market_data = await self._get_market_intelligence_data()
        alerts, wall_hold_updates = await self.market_intelligence.run_all_checks(market_data, session_state, settings)
        dedup_updates = await self._process_alerts(user, settings, session_state, alerts)

        # Persist the latest spot/PCR/VIX as the reference point for the NEXT
        # check_market_conditions call (index-move and wall-break diff
        # against the prior poll, not the session open — matches the
        # existing prev_spot convention in check_wall_break), plus this
        # poll's wall-hold-since/confirmed state (Priority 1, 2026-07-10;
        # time-based — Piece C, 2026-07-11).
        # Piece B diagnostic (2026-07-11) — did this check's spot come from
        # LivePriceCache or the REST fallback? get_monitor_status() surfaces
        # this so it's answerable without SSHing into the Oracle VM.
        await self.repo.save_session_state(user["id"], {
            "last_nifty_spot": market_data.get("nifty_spot") or session_state.get("last_nifty_spot"),
            "last_sensex_spot": market_data.get("sensex_spot") or session_state.get("last_sensex_spot"),
            "live_price_nifty_ltp": market_data.get("nifty_spot") or None,
            "live_price_nifty_cache_hit": bool(market_data.get("nifty_spot_cache_hit")),
            "live_price_sensex_ltp": market_data.get("sensex_spot") or None,
            "live_price_sensex_cache_hit": bool(market_data.get("sensex_spot_cache_hit")),
            "live_price_checked_at": datetime.now(timezone.utc).isoformat(),
            **wall_hold_updates,
            **dedup_updates,
        })

    async def _on_index_tick(self, symbol: str, ltp: float) -> None:
        """Piece C (2026-07-11) — fired by LivePriceCache the instant NIFTY/
        SENSEX ticks. Evaluates index-move and (NIFTY only) wall-hold-
        duration against the last-known reference values, through the same
        cooldown/dedup/delivery path as the poll loop (_process_alerts).

        PCR/macro/pinning-risk stay poll-only — there is no WS feed for OI,
        only spot, so those checks only get fresher/more-reliable data at
        poll time; they don't get faster ticks. Wall LEVELS (open_call_wall/
        open_put_wall) are the session-open reference, same as the poll
        path uses — only the hold-duration clock and the spot comparison
        are now continuous.
        """
        if symbol not in ("NIFTY", "SENSEX"):
            return  # e.g. a position's underlying, subscribed via extra_symbols
        ctx = self._market_context
        if not ctx:
            return  # not yet primed by a first check_market_conditions() poll
        user = ctx["user"]
        settings = ctx["settings"]

        async with self._index_lock(symbol):
            session_state = await self.repo.get_session_state(user["id"])
            if not session_state:
                return
            now = datetime.now(timezone.utc)

            updates: dict = {}
            if symbol == "NIFTY":
                prev_nifty = session_state.get("last_nifty_spot")
                last_sensex = session_state.get("last_sensex_spot")
                idx_alerts = self.market_intelligence.check_index_movement(
                    ltp, prev_nifty, last_sensex or 0.0, last_sensex, settings,
                )
                call_wall = session_state.get("open_call_wall")
                put_wall = session_state.get("open_put_wall")
                wall_alerts, wall_updates = self.market_intelligence.check_oi_walls(
                    ltp, prev_nifty, call_wall, put_wall, session_state, settings, now=now,
                )
                alerts = idx_alerts + wall_alerts
                updates = {**wall_updates, "last_nifty_spot": ltp}
            else:  # SENSEX
                prev_sensex = session_state.get("last_sensex_spot")
                last_nifty = session_state.get("last_nifty_spot")
                alerts = self.market_intelligence.check_index_movement(
                    last_nifty or 0.0, last_nifty, ltp, prev_sensex, settings,
                )
                updates = {"last_sensex_spot": ltp}

            dedup_updates = await self._process_alerts(user, settings, session_state, alerts)
            await self.repo.save_session_state(user["id"], {**updates, **dedup_updates})

    async def check_mcx_session_close_risk(self, user: dict) -> None:
        """Priority B7 (2026-07-11) — proactively push a Telegram alert when
        an MCX position is open and untracked (no MCX symbol resolution
        exists yet, see docs/research/mcx_scope_20260711.md, so every MCX
        position is genuinely unmonitored by this platform's trailing-SL
        system today) and MCX's close is within the hour. Runs regardless
        of is_market_open() — the whole point is catching the gap after NSE
        closes but before MCX does, when the main loop's checks have
        already gone idle.

        Reads INDmoney's raw positions directly (not the monitor's tracked
        positions, which never contain MCX rows) since that's this
        platform's real, working position-data source for MCX trades.
        """
        from src.brokers.indmoney import INDmoneyBroker

        try:
            ind = INDmoneyBroker()
            if not await ind.is_authenticated():
                return
            positions = await ind.get_positions()
        except Exception as exc:
            logger.debug("check_mcx_session_close_risk: could not fetch INDmoney positions: %s", exc)
            return

        settings = await self.repo.get_user_settings(user["id"])
        cooldown_seconds = settings.get("cooldown_session_close_risk", 3600)
        now_naive = datetime.now(self.IST).replace(tzinfo=None)
        for pos in positions:
            if pos.quantity == 0:
                continue
            triggered, note = self.conditions.check_session_close_risk(
                exchange=pos.exchange,
                has_sl_or_target=False,  # every MCX position is untracked today — see docstring
                now=now_naive,
                exchange_close_time=self.MCX_CLOSE,
            )
            if not triggered:
                continue

            last_sent = await self.repo.get_last_alert_time(user["id"], "session_close_risk", pos.symbol)
            if self.conditions.is_alert_on_cooldown(last_sent, cooldown_seconds):
                continue

            message = f"{pos.symbol}: {note}"
            delivered = await self.alerter.send_macro_alert(user, "session_close_risk", message)
            await self.repo.save_alert(user["id"], {
                "alert_type": "session_close_risk",
                "symbol": pos.symbol,
                "message": message,
                "severity": "high",
                "delivered": delivered,
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

                # Priority B7 (2026-07-11) — deliberately OUTSIDE the
                # is_market_open() gate above: MCX trades until 23:30 IST,
                # so this must keep firing after NSE's 15:30 close, which is
                # exactly the window where a commodity position previously
                # went unmonitored.
                if self.is_mcx_session_active():
                    await self.check_mcx_session_close_risk(user)

            positions = await self.repo.get_active_positions(users[0]["id"]) if users else []
            min_dte = min((p.get("dte", 7) for p in positions), default=7)
            max_premium = max((p.get("current_premium", 0) for p in positions), default=0)
            interval = self.get_poll_interval(min_dte, max_premium)

            # Piece B (2026-07-11) — refresh which instruments the live-price
            # cache is subscribed to now that this tick's position set is
            # known, so the NEXT tick's check_market_conditions can read
            # NIFTY/SENSEX spot from here instead of a fresh REST call. A
            # brand-new position not yet subscribed just falls through to the
            # existing REST path on its first tick (see LivePriceCache.get()).
            try:
                await self.live_prices.refresh_subscriptions([p["symbol"] for p in positions])
            except Exception as exc:
                logger.warning("live_prices.refresh_subscriptions failed: %s", exc)

            await asyncio.sleep(interval)

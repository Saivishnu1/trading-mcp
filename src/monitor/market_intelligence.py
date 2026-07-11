"""Phase 9B — proactive market intelligence checks for the monitor.

Wired into MarketMonitor.check_market_conditions() (scheduler.py). Every
check is observation-only: a factual description of what moved and by how
much, never a buy/sell signal, price target, or confidence score (see
src/monitor/conditions.py's module docstring — the same rule applies here).

All checks reuse the existing, tested MarketConditions primitives
(check_pcr_shift, check_vix_spike, check_wall_break, check_index_move,
check_asset_move, check_risk_off_alignment) rather than duplicating
threshold logic — this module is just orchestration: fetch live data,
diff it against session_state, and call the right condition check.
"""
from __future__ import annotations

import asyncio
import logging

from src.monitor.conditions import MarketConditions

logger = logging.getLogger(__name__)

# Default thresholds — overridden per-user by monitor.settings columns
# (crude_move_threshold, gold_move_threshold, nifty_move_threshold,
# sensex_move_threshold, risk_off_count_threshold, pcr_shift_threshold,
# vix_spike_threshold). Used only when a settings row/column is missing.
_DEFAULT_THRESHOLDS = {
    "crude_move_threshold": 2.0,
    "gold_move_threshold": 1.5,
    "nifty_move_threshold": 1.0,
    "sensex_move_threshold": 1.0,
    "vix_spike_threshold": 14.0,
    "pcr_shift_threshold": 0.3,
    "risk_off_count_threshold": 3,
}


class MarketIntelligence:
    """Stateless orchestrator — takes already-fetched data + session_state/
    settings dicts and returns a list of alert dicts. Does not fetch data or
    touch the repository itself (the scheduler owns I/O and persistence),
    which keeps this class trivial to unit-test without mocking HTTP/DB."""

    def __init__(self, conditions: MarketConditions | None = None):
        self.conditions = conditions or MarketConditions()

    def check_macro_signals(self, global_pulse: dict, settings: dict) -> list[dict]:
        """Crude/gold/S&P moves and a combined risk-off alignment count.
        global_pulse is the raw get_global_pulse() dict — nested under
        "assets" (assets.crude_oil.change_pct etc.), not top-level fields."""
        alerts: list[dict] = []
        if not isinstance(global_pulse, dict) or "error" in global_pulse:
            return alerts

        assets = global_pulse.get("assets") or {}
        crude_change = float((assets.get("crude_oil") or {}).get("change_pct") or 0)
        gold_change = float((assets.get("gold") or {}).get("change_pct") or 0)
        sp500_change = float((assets.get("sp500") or {}).get("change_pct") or 0)

        crude_threshold = settings.get("crude_move_threshold") or _DEFAULT_THRESHOLDS["crude_move_threshold"]
        gold_threshold = settings.get("gold_move_threshold") or _DEFAULT_THRESHOLDS["gold_move_threshold"]

        triggered, reason = self.conditions.check_asset_move("Crude", crude_change, crude_threshold)
        if triggered:
            alerts.append({
                "type": "macro_crude",
                "severity": "high" if abs(crude_change) > crude_threshold * 1.5 else "medium",
                "symbol": "CRUDE",
                "message": reason,
                "cooldown_key": "cooldown_macro",
            })

        triggered, reason = self.conditions.check_asset_move("Gold", gold_change, gold_threshold)
        if triggered:
            alerts.append({
                "type": "macro_gold",
                "severity": "medium",
                "symbol": "GOLD",
                "message": reason,
                "cooldown_key": "cooldown_macro",
            })

        risk_off_signals = {
            "crude_up": crude_change > 2,
            "gold_up": gold_change > 1.5,
            "sp500_down": sp500_change < -1,
        }
        min_count = int(settings.get("risk_off_count_threshold") or _DEFAULT_THRESHOLDS["risk_off_count_threshold"])
        triggered, reason = self.conditions.check_risk_off_alignment(risk_off_signals, min_count)
        if triggered:
            alerts.append({
                "type": "macro_risk_off",
                "severity": "critical",
                "symbol": "MARKET",
                "message": (
                    f"{reason}\n"
                    f"Crude {crude_change:+.1f}% | Gold {gold_change:+.1f}% | S&P {sp500_change:+.1f}%"
                ),
                "cooldown_key": "cooldown_macro",
            })

        return alerts

    def check_vix(self, current_vix: float, open_vix: float | None, settings: dict) -> list[dict]:
        if open_vix is None or not current_vix:
            return []
        threshold = settings.get("vix_spike_threshold") or _DEFAULT_THRESHOLDS["vix_spike_threshold"]
        triggered, reason = self.conditions.check_vix_spike(current_vix, open_vix, threshold)
        if not triggered:
            return []
        return [{
            "type": "macro_vix",
            "severity": "high",
            "symbol": "VIX",
            "message": reason,
            "cooldown_key": "cooldown_vix",
        }]

    def check_index_movement(
        self, nifty_spot: float, last_nifty_spot: float | None,
        sensex_spot: float, last_sensex_spot: float | None,
        settings: dict,
    ) -> list[dict]:
        """Moves since the LAST CHECK (not session open) — matches the
        wall-break convention of diffing against the prior poll."""
        alerts: list[dict] = []
        nifty_threshold = settings.get("nifty_move_threshold") or _DEFAULT_THRESHOLDS["nifty_move_threshold"]
        sensex_threshold = settings.get("sensex_move_threshold") or _DEFAULT_THRESHOLDS["sensex_move_threshold"]

        if last_nifty_spot and nifty_spot:
            triggered, reason = self.conditions.check_index_move("NIFTY", nifty_spot, last_nifty_spot, nifty_threshold)
            if triggered:
                alerts.append({
                    "type": "index_move_nifty",
                    "severity": "high",
                    "symbol": "NIFTY",
                    "message": reason,
                    "cooldown_key": "cooldown_pcr",
                })

        if last_sensex_spot and sensex_spot:
            triggered, reason = self.conditions.check_index_move("SENSEX", sensex_spot, last_sensex_spot, sensex_threshold)
            if triggered:
                alerts.append({
                    "type": "index_move_sensex",
                    "severity": "high",
                    "symbol": "SENSEX",
                    "message": reason,
                    "cooldown_key": "cooldown_pcr",
                })

        return alerts

    def check_oi_walls(
        self, spot: float, prev_spot: float | None,
        call_wall: float | None, put_wall: float | None,
        session_state: dict | None = None, settings: dict | None = None,
    ) -> tuple[list[dict], dict]:
        """Hold-confirmation wall-break check (Priority 1 fix, 2026-07-10).

        A single-poll cross used to fire oi_call_wall_break/oi_put_wall_break
        immediately, which re-fired on every whipsaw across the same level.
        Now the raw touch only updates a per-wall streak counter in
        session_state; the Telegram-bound alert fires only once the streak
        holds for `wall_break_confirm_candles` consecutive polls, and a
        symmetric oi_wall_rejection fires if spot reverts before that.

        Returns (alerts, streak_updates) — streak_updates is always returned
        (even when empty) so callers persist it via save_session_state
        regardless of whether an alert fired this poll.
        """
        session_state = session_state or {}
        settings = settings or {}
        streak_updates: dict = {}

        if not prev_spot or not call_wall or not put_wall:
            return [], streak_updates

        confirm_candles = int(settings.get("wall_break_confirm_candles") or 3)
        alerts: list[dict] = []

        touched, touch_reason = self.conditions.check_wall_break(spot, prev_spot, call_wall, put_wall)
        if touched:
            alert_type = "oi_call_wall_break" if "call wall" in touch_reason else "oi_put_wall_break"
            alerts.append({
                "type": alert_type,
                "severity": "low",
                "symbol": "NIFTY",
                "message": touch_reason,
                "cooldown_key": "cooldown_wall_break",
                "delivered": False,
            })

        for wall_name, wall_level, direction, hold_type, reject_type in (
            ("call", call_wall, "above", "oi_call_wall_break", "oi_wall_rejection"),
            ("put", put_wall, "below", "oi_put_wall_break", "oi_wall_rejection"),
        ):
            streak_key = f"{wall_name}_wall_break_streak"
            confirmed_key = f"{wall_name}_wall_break_confirmed"
            prev_streak = int(session_state.get(streak_key) or 0)
            was_confirmed = bool(session_state.get(confirmed_key) or False)

            new_streak = self.conditions.update_wall_break_streak(spot, wall_level, prev_streak, direction)
            streak_updates[streak_key] = new_streak

            if self.conditions.check_wall_hold(new_streak, confirm_candles) and not was_confirmed:
                alerts.append({
                    "type": hold_type,
                    "severity": "high",
                    "symbol": "NIFTY",
                    "message": f"Spot held beyond {wall_name} wall at {wall_level} for {new_streak} consecutive checks",
                    "cooldown_key": "cooldown_wall_break",
                    # Priority B3 (2026-07-11) — dedup on spot's distance from
                    # the wall at the moment of firing, not just cooldown.
                    "dedup_key": f"last_fired_{wall_name}_wall_break_spot",
                    "value": spot,
                })
                streak_updates[confirmed_key] = True
            elif was_confirmed and new_streak == 0:
                streak_updates[confirmed_key] = False
            elif not was_confirmed and self.conditions.check_wall_rejection(prev_streak, new_streak):
                alerts.append({
                    "type": reject_type,
                    "severity": "medium",
                    "symbol": "NIFTY",
                    "message": f"Spot broke {wall_name} wall at {wall_level} then reverted within {confirm_candles} checks",
                    "cooldown_key": "cooldown_wall_break",
                })

        return alerts, streak_updates

    def check_pinning_risk(
        self, spot: float | None, max_pain: float | None, is_expiry_week: bool, settings: dict,
    ) -> list[dict]:
        """Priority 3 (2026-07-10) — proactively alert once when spot enters
        max-pain pinning range intraday during expiry week, instead of this
        only surfacing via a manual deep pull of the composite tool."""
        from src.options.analytics import check_pinning_risk as _check_pinning_risk

        threshold_pct = settings.get("pinning_risk_threshold_pct") or 0.5
        result = _check_pinning_risk(spot, max_pain, is_expiry_week, threshold_pct)
        if not result["active"]:
            return []
        return [{
            "type": "pinning_risk",
            "severity": "medium",
            "symbol": "NIFTY",
            "message": (
                f"Spot within {result['distance_points']:.0f} points of max pain "
                f"({max_pain:.0f}) — expect range-bound chop until expiry unwinds "
                f"OI concentration."
            ),
            "cooldown_key": "cooldown_pinning",
        }]

    def check_pcr_shift(self, current_pcr: float | None, open_pcr: float | None, settings: dict) -> list[dict]:
        if current_pcr is None or open_pcr is None:
            return []
        threshold = settings.get("pcr_shift_threshold") or _DEFAULT_THRESHOLDS["pcr_shift_threshold"]
        triggered, reason = self.conditions.check_pcr_shift(current_pcr, open_pcr, threshold)
        if not triggered:
            return []
        return [{
            "type": "pcr_shift",
            "severity": "medium",
            "symbol": "NIFTY",
            "message": reason,
            "cooldown_key": "cooldown_pcr",
            # Priority B3 (2026-07-11) — dedup key/value so the scheduler can
            # gate on "differs from the last FIRED value", not just cooldown.
            "dedup_key": "last_fired_pcr",
            "value": current_pcr,
        }]

    async def run_all_checks(self, market_data: dict, session_state: dict, settings: dict) -> tuple[list[dict], dict]:
        """market_data carries already-fetched values (the caller/scheduler
        owns all I/O): global_pulse, vix, nifty_spot, sensex_spot, nifty_pcr,
        nifty_call_wall, nifty_put_wall. Never raises — a broken sub-check
        is logged and skipped so one bad source can't take down the others.

        Returns (alerts, wall_break_streak_updates) — the second element
        holds call_wall_break_streak/put_wall_break_streak/*_confirmed
        updates from check_oi_walls that the caller must persist via
        save_session_state, independent of whether any alert fired."""

        def _safe(fn, *args):
            try:
                return fn(*args)
            except Exception as exc:
                logger.warning("market_intelligence check %s failed: %s", getattr(fn, "__name__", fn), exc)
                return []

        def _safe_oi_walls(*args):
            try:
                return self.check_oi_walls(*args)
            except Exception as exc:
                logger.warning("market_intelligence check check_oi_walls failed: %s", exc)
                return [], {}

        results = await asyncio.gather(
            asyncio.to_thread(_safe, self.check_macro_signals, market_data.get("global_pulse") or {}, settings),
            asyncio.to_thread(_safe, self.check_vix, market_data.get("vix") or 0.0, session_state.get("open_vix"), settings),
            asyncio.to_thread(
                _safe, self.check_index_movement,
                market_data.get("nifty_spot") or 0.0, session_state.get("last_nifty_spot"),
                market_data.get("sensex_spot") or 0.0, session_state.get("last_sensex_spot"),
                settings,
            ),
            asyncio.to_thread(
                _safe_oi_walls,
                market_data.get("nifty_spot") or 0.0, session_state.get("last_nifty_spot"),
                session_state.get("open_call_wall"), session_state.get("open_put_wall"),
                session_state, settings,
            ),
            asyncio.to_thread(_safe, self.check_pcr_shift, market_data.get("nifty_pcr"), session_state.get("open_pcr"), settings),
            asyncio.to_thread(
                _safe, self.check_pinning_risk,
                market_data.get("nifty_spot"), market_data.get("nifty_max_pain"),
                bool(market_data.get("nifty_is_expiry_week")), settings,
            ),
            return_exceptions=True,
        )

        all_alerts: list[dict] = []
        streak_updates: dict = {}
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.warning("market_intelligence run_all_checks sub-check raised: %s", result)
            elif i == 3:  # check_oi_walls returns (alerts, streak_updates)
                oi_alerts, streak_updates = result
                all_alerts.extend(oi_alerts)
            elif isinstance(result, list):
                all_alerts.extend(result)
        return all_alerts, streak_updates

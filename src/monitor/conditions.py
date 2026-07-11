"""Observation-only market/position condition checks for the monitor.

Every check returns (triggered, message) — messages are factual observations,
never recommendations ("consider booking" etc. is explicitly out of scope).
"""
from __future__ import annotations

from datetime import datetime, time


class MarketConditions:

    def check_trailing_sl(self, current: float, trailing_sl: float) -> tuple[bool, str]:
        if current <= trailing_sl:
            return True, f"Trailing SL breached — premium {current} below SL {trailing_sl}"
        return False, ""

    def check_profit_milestone(self, entry: float, current: float, threshold_pct: float) -> tuple[bool, str]:
        pct = (current - entry) / entry * 100
        if pct >= threshold_pct * 100:
            return True, f"Position profit reached +{pct:.0f}%"
        return False, ""

    def check_pcr_shift(self, current_pcr: float, open_pcr: float, threshold: float) -> tuple[bool, str]:
        shift = abs(current_pcr - open_pcr)
        if shift >= threshold:
            direction = "bullish" if current_pcr > open_pcr else "bearish"
            return True, f"PCR shifted {shift:.2f} — {direction} ({open_pcr:.2f} to {current_pcr:.2f})"
        return False, ""

    def check_vix_spike(self, current_vix: float, open_vix: float, threshold: float) -> tuple[bool, str]:
        if current_vix >= threshold and current_vix > open_vix * 1.1:
            return True, f"VIX at {current_vix} (opened {open_vix})"
        return False, ""

    def check_wall_break(self, spot: float, prev_spot: float, call_wall: float, put_wall: float) -> tuple[bool, str]:
        if prev_spot < call_wall <= spot:
            return True, f"Spot broke call wall at {call_wall}"
        if prev_spot > put_wall >= spot:
            return True, f"Spot broke put wall at {put_wall}"
        return False, ""

    def update_wall_break_streak(self, spot: float, wall: float, streak: int, direction: str) -> int:
        """direction: 'above' (call wall) means the streak continues while
        spot stays at/beyond the wall; 'below' (put wall) means it continues
        while spot stays at/beneath it. Returns the new streak count —
        incremented while still beyond, reset to 0 once spot falls back
        inside the wall."""
        beyond = spot >= wall if direction == "above" else spot <= wall
        return streak + 1 if beyond else 0

    def check_wall_hold(self, streak: int, confirm_candles: int) -> bool:
        """True once spot has stayed beyond the wall for at least
        `confirm_candles` consecutive polls — the hold-confirmation gate
        that keeps a single momentary cross from reaching Telegram."""
        return streak >= confirm_candles

    def check_wall_rejection(self, prev_streak: int, new_streak: int) -> bool:
        """True exactly on the touch-then-fail transition: a streak that was
        building (prev_streak > 0) just reset to 0 (new_streak == 0) without
        ever reaching the hold threshold. Callers must gate on this already
        having not been confirmed — a reversal AFTER confirmation is not a
        rejection, it's just the confirmed break ending."""
        return prev_streak > 0 and new_streak == 0

    def check_index_move(self, index: str, current: float, reference: float, threshold_pct: float) -> tuple[bool, str]:
        """Percentage move of an index (NIFTY/SENSEX) since the last check,
        observed fact only — no direction implied beyond the arithmetic sign."""
        if not reference:
            return False, ""
        change_pct = (current - reference) / reference * 100
        if abs(change_pct) >= threshold_pct:
            return True, f"{index} moved {change_pct:+.1f}% ({reference:.0f} to {current:.0f})"
        return False, ""

    def check_asset_move(self, name: str, change_pct: float, threshold_pct: float) -> tuple[bool, str]:
        """Percentage move of a global macro asset (crude/gold/S&P) already
        expressed as a change_pct by the data source (get_global_pulse)."""
        if abs(change_pct) >= threshold_pct:
            return True, f"{name} moved {change_pct:+.1f}%"
        return False, ""

    def check_risk_off_alignment(self, signals: dict[str, bool], min_count: int) -> tuple[bool, str]:
        """Multiple independent macro signals aligned in the same risk-off
        direction — a factual count, not a directional call. `signals` maps a
        label to whether that signal is currently active (e.g. {"crude_up": True}).
        """
        active = [label for label, is_active in signals.items() if is_active]
        if len(active) >= min_count:
            return True, f"{len(active)}/{len(signals)} risk-off signals active: {', '.join(active)}"
        return False, ""

    def is_alert_on_cooldown(self, last_sent: datetime | None, cooldown_seconds: int) -> bool:
        if last_sent is None:
            return False
        return (datetime.now(last_sent.tzinfo) - last_sent).total_seconds() < cooldown_seconds

    def check_dedup_gate(
        self,
        current_value: float,
        last_fired_value: float | None,
        minutes_since_last_fire: float | None,
        min_delta: float,
        min_minutes: float,
    ) -> bool:
        """Priority B3 (2026-07-11) — near-duplicate re-fire guard, distinct
        from the coarser cooldown floor: only allow a re-fire if the value
        has moved meaningfully from what was last actually fired (not the
        session-open reference), OR enough time has passed regardless of
        delta. Prevents e.g. PCR 1.21 -> 1.22 re-firing 15 minutes apart just
        because both individually cleared the open-PCR threshold.

        True (allowed to fire) when there is no prior fired value/time (first
        fire ever), when the delta exceeds min_delta, OR when enough time has
        passed since the last fire — matches the spec's explicit OR."""
        if last_fired_value is None or minutes_since_last_fire is None:
            return True
        if abs(current_value - last_fired_value) > min_delta:
            return True
        return minutes_since_last_fire > min_minutes

    def check_session_close_risk(
        self,
        exchange: str,
        has_sl_or_target: bool,
        now: datetime,
        exchange_close_time: time,
        warn_minutes_before: int = 60,
    ) -> tuple[bool, str]:
        """Priority B7 (2026-07-11) — flag an MCX (or any extended-hours
        exchange) position that has no SL/target set and whose exchange is
        closing within `warn_minutes_before` minutes. NSE/BSE close at
        15:30 IST, well before attention typically shifts elsewhere; MCX
        trades until 23:30 IST, past when a position can go unmonitored
        into the close without anyone noticing.

        `now`/`exchange_close_time` are both naive local (IST) values — the
        caller is responsible for timezone conversion, matching this
        module's existing observation-only, no-I/O style."""
        if exchange.upper() != "MCX" or has_sl_or_target:
            return False, ""

        close_dt = datetime.combine(now.date(), exchange_close_time)
        if now >= close_dt:
            return False, ""

        minutes_to_close = (close_dt - now).total_seconds() / 60
        if minutes_to_close > warn_minutes_before:
            return False, ""

        return True, (
            f"MCX position has no SL/target set and the exchange closes in "
            f"{int(minutes_to_close)} minutes."
        )

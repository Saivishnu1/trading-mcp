"""Observation-only market/position condition checks for the monitor.

Every check returns (triggered, message) — messages are factual observations,
never recommendations ("consider booking" etc. is explicitly out of scope).
"""
from __future__ import annotations

from datetime import datetime


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

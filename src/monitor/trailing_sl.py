"""Trailing stop-loss calculation for monitored option positions.

Pure functions — no I/O. Base % scales by days-to-expiry, then adjusted for
moneyness and India VIX.
"""
from __future__ import annotations


class TrailingSLCalculator:

    def calculate_pct(self, dte: int, moneyness: str, vix: float) -> float:
        if dte == 0:
            base = 0.05
        elif dte == 1:
            base = 0.08
        elif dte <= 3:
            base = 0.12
        elif dte <= 7:
            base = 0.15
        else:
            base = 0.20

        if moneyness == "OTM":
            base *= 0.8
        elif moneyness == "ITM":
            base *= 1.2

        if vix > 20:
            base *= 1.3
        elif vix < 12:
            base *= 0.9

        return round(base, 3)

    def get_trailing_sl_price(self, peak_premium: float, dte: int, moneyness: str, vix: float) -> float:
        pct = self.calculate_pct(dte, moneyness, vix)
        return round(peak_premium * (1 - pct), 2)

    def get_moneyness(self, spot: float, strike: float, option_type: str) -> str:
        diff_pct = abs(spot - strike) / spot * 100
        if diff_pct < 0.5:
            return "ATM"
        if option_type == "CE":
            return "ITM" if spot > strike else "OTM"
        return "ITM" if spot < strike else "OTM"

    def should_stop_monitoring(self, current_premium: float, entry_premium: float) -> bool:
        return current_premium < entry_premium * 0.10

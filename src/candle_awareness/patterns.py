"""
Candlestick pattern data classes and high-level detector orchestrator.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass
class CandlePattern:
    name: str
    pattern_type: str   # "bullish" | "bearish" | "neutral"
    strength: str       # "strong" | "moderate" | "weak"
    location: int       # bars from end (0 = latest bar)
    bar_date: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    volume_ratio: float
    context: str = ""


class PatternDetector:
    """Orchestrates all pattern detectors over a candle DataFrame."""

    def detect_all(self, df: pd.DataFrame) -> list[CandlePattern]:
        """Run all detectors on the last 10 bars. Returns detected patterns."""
        if df is None or len(df) < 2:
            return []

        # Work on last 10 bars only (enough for 3-candle patterns)
        window = df.iloc[-10:].reset_index(drop=True)
        avg_vol = float(df["volume"].replace(0, float("nan")).mean() or 1)

        from .detector import SingleCandleDetectors, TwoCandleDetectors, ThreeCandleDetectors

        single = SingleCandleDetectors()
        two = TwoCandleDetectors()
        three = ThreeCandleDetectors()

        results: list[CandlePattern] = []

        n = len(window)
        for i in range(n):
            c = window.iloc[i]
            bar_date = str(c.get("datetime", ""))[:10]
            location = n - 1 - i  # 0 = last bar

            def _vol_ratio(row) -> float:
                v = float(row.get("volume", 0) or 0)
                return round(v / avg_vol, 2) if avg_vol > 0 else 0.0

            # --- Single-candle ---
            detected = single.detect(c)
            for name, ptype in detected:
                results.append(CandlePattern(
                    name=name, pattern_type=ptype, strength="weak",
                    location=location, bar_date=bar_date,
                    open=float(c["open"]), high=float(c["high"]),
                    low=float(c["low"]), close=float(c["close"]),
                    volume=float(c.get("volume", 0) or 0),
                    volume_ratio=_vol_ratio(c),
                ))

            # --- Two-candle (need i >= 1) ---
            if i >= 1:
                prev = window.iloc[i - 1]
                detected2 = two.detect(prev, c)
                for name, ptype in detected2:
                    results.append(CandlePattern(
                        name=name, pattern_type=ptype, strength="weak",
                        location=location, bar_date=bar_date,
                        open=float(c["open"]), high=float(c["high"]),
                        low=float(c["low"]), close=float(c["close"]),
                        volume=float(c.get("volume", 0) or 0),
                        volume_ratio=_vol_ratio(c),
                    ))

            # --- Three-candle (need i >= 2) ---
            if i >= 2:
                p2 = window.iloc[i - 2]
                p1 = window.iloc[i - 1]
                detected3 = three.detect(p2, p1, c)
                for name, ptype in detected3:
                    results.append(CandlePattern(
                        name=name, pattern_type=ptype, strength="weak",
                        location=location, bar_date=bar_date,
                        open=float(c["open"]), high=float(c["high"]),
                        low=float(c["low"]), close=float(c["close"]),
                        volume=float(c.get("volume", 0) or 0),
                        volume_ratio=_vol_ratio(c),
                    ))

        return results

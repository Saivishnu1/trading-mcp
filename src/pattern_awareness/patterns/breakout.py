"""
Breakout chart pattern detectors.
"""
from __future__ import annotations

import pandas as pd

_MIN_TOUCHES = 2   # minimum trendline touches


def _bar_date(df: pd.DataFrame, idx: int) -> str:
    return str(df["datetime"].iloc[idx])[:10]


def _find_local_highs(df: pd.DataFrame, window: int = 3) -> list[int]:
    highs = []
    for i in range(window, len(df) - window):
        if df["high"].iloc[i] == df["high"].iloc[i - window: i + window + 1].max():
            highs.append(i)
    return highs


def _find_local_lows(df: pd.DataFrame, window: int = 3) -> list[int]:
    lows = []
    for i in range(window, len(df) - window):
        if df["low"].iloc[i] == df["low"].iloc[i - window: i + window + 1].min():
            lows.append(i)
    return lows


class BreakoutPatterns:

    @staticmethod
    def detect_ascending_triangle(df: pd.DataFrame) -> list[dict]:
        """Flat resistance + rising lows, ≥2 touches each."""
        if len(df) < 10:
            return []

        peaks = _find_local_highs(df)
        lows_idx = _find_local_lows(df)
        if len(peaks) < _MIN_TOUCHES or len(lows_idx) < _MIN_TOUCHES:
            return []

        # Flat resistance: top peaks within 1%
        peak_vals = [df["high"].iloc[i] for i in peaks]
        resistance = max(peak_vals)
        flat = sum(1 for p in peak_vals if abs(p - resistance) / resistance <= 0.01)
        if flat < _MIN_TOUCHES:
            return []

        # Rising lows: each successive low higher than previous
        low_vals = [df["low"].iloc[i] for i in lows_idx]
        rising = sum(1 for a, b in zip(low_vals, low_vals[1:]) if b > a)
        if rising < _MIN_TOUCHES - 1:
            return []

        support = min(low_vals)
        current_close = df["close"].iloc[-1]
        if current_close > resistance:
            status = "confirmed"
        elif lows_idx[-1] > peaks[-1]:
            status = "complete"
        else:
            status = "forming"

        return [{
            "pattern": "Ascending Triangle",
            "type": "breakout",
            "direction": "bullish",
            "status": status,
            "support": round(support, 2),
            "resistance": round(resistance, 2),
            "neckline": round(resistance, 2),
            "start_date": _bar_date(df, min(peaks[0], lows_idx[0])),
            "end_date": _bar_date(df, max(peaks[-1], lows_idx[-1])),
            "bars_formed": max(peaks[-1], lows_idx[-1]) - min(peaks[0], lows_idx[0]),
            "observations": [
                f"Flat resistance near {resistance:,.2f} ({flat} touches)",
                f"Rising lows from {low_vals[0]:,.2f} to {low_vals[-1]:,.2f}",
            ],
        }]

    @staticmethod
    def detect_descending_triangle(df: pd.DataFrame) -> list[dict]:
        """Flat support + falling highs, ≥2 touches each."""
        if len(df) < 10:
            return []

        peaks = _find_local_highs(df)
        lows_idx = _find_local_lows(df)
        if len(peaks) < _MIN_TOUCHES or len(lows_idx) < _MIN_TOUCHES:
            return []

        # Flat support: bottom lows within 1%
        low_vals = [df["low"].iloc[i] for i in lows_idx]
        support = min(low_vals)
        flat = sum(1 for l in low_vals if abs(l - support) / max(support, 1e-9) <= 0.01)
        if flat < _MIN_TOUCHES:
            return []

        # Falling highs
        peak_vals = [df["high"].iloc[i] for i in peaks]
        falling = sum(1 for a, b in zip(peak_vals, peak_vals[1:]) if b < a)
        if falling < _MIN_TOUCHES - 1:
            return []

        resistance = max(peak_vals)
        current_close = df["close"].iloc[-1]
        if current_close < support:
            status = "confirmed"
        elif peaks[-1] > lows_idx[-1]:
            status = "complete"
        else:
            status = "forming"

        return [{
            "pattern": "Descending Triangle",
            "type": "breakout",
            "direction": "bearish",
            "status": status,
            "support": round(support, 2),
            "resistance": round(resistance, 2),
            "neckline": round(support, 2),
            "start_date": _bar_date(df, min(peaks[0], lows_idx[0])),
            "end_date": _bar_date(df, max(peaks[-1], lows_idx[-1])),
            "bars_formed": max(peaks[-1], lows_idx[-1]) - min(peaks[0], lows_idx[0]),
            "observations": [
                f"Flat support near {support:,.2f} ({flat} touches)",
                f"Falling highs from {peak_vals[0]:,.2f} to {peak_vals[-1]:,.2f}",
            ],
        }]

    @staticmethod
    def detect_symmetrical_triangle(df: pd.DataFrame) -> list[dict]:
        """Lower highs + higher lows converging, ≥2 touches each side."""
        if len(df) < 10:
            return []

        peaks = _find_local_highs(df)
        lows_idx = _find_local_lows(df)
        if len(peaks) < _MIN_TOUCHES or len(lows_idx) < _MIN_TOUCHES:
            return []

        peak_vals = [df["high"].iloc[i] for i in peaks]
        low_vals = [df["low"].iloc[i] for i in lows_idx]

        falling_highs = sum(1 for a, b in zip(peak_vals, peak_vals[1:]) if b < a)
        rising_lows = sum(1 for a, b in zip(low_vals, low_vals[1:]) if b > a)

        if falling_highs < _MIN_TOUCHES - 1 or rising_lows < _MIN_TOUCHES - 1:
            return []

        resistance = peak_vals[-1]
        support = low_vals[-1]
        apex = (resistance + support) / 2
        current_close = df["close"].iloc[-1]

        if current_close > resistance:
            status = "confirmed"
            direction = "bullish"
        elif current_close < support:
            status = "confirmed"
            direction = "bearish"
        else:
            status = "forming"
            direction = "neutral"

        return [{
            "pattern": "Symmetrical Triangle",
            "type": "breakout",
            "direction": direction,
            "status": status,
            "support": round(support, 2),
            "resistance": round(resistance, 2),
            "neckline": round(apex, 2),
            "start_date": _bar_date(df, min(peaks[0], lows_idx[0])),
            "end_date": _bar_date(df, max(peaks[-1], lows_idx[-1])),
            "bars_formed": max(peaks[-1], lows_idx[-1]) - min(peaks[0], lows_idx[0]),
            "observations": [
                f"Converging trendlines — apex near {apex:,.2f}",
                f"Highs falling from {peak_vals[0]:,.2f}, lows rising from {low_vals[0]:,.2f}",
            ],
        }]

    @staticmethod
    def detect_wedge(df: pd.DataFrame) -> list[dict]:
        """Rising or falling wedge: both trendlines slope same direction but converge."""
        if len(df) < 12:
            return []

        peaks = _find_local_highs(df)
        lows_idx = _find_local_lows(df)
        if len(peaks) < 3 or len(lows_idx) < 3:
            return []

        peak_vals = [df["high"].iloc[i] for i in peaks[-3:]]
        low_vals = [df["low"].iloc[i] for i in lows_idx[-3:]]

        # Rising wedge: both trendlines sloping up, converging
        highs_rising = peak_vals[-1] > peak_vals[0]
        lows_rising = low_vals[-1] > low_vals[0]
        high_slope = (peak_vals[-1] - peak_vals[0]) / max(len(peaks) - 1, 1)
        low_slope = (low_vals[-1] - low_vals[0]) / max(len(lows_idx) - 1, 1)

        is_rising_wedge = highs_rising and lows_rising and low_slope > high_slope
        is_falling_wedge = (not highs_rising) and (not lows_rising) and high_slope < low_slope

        if not (is_rising_wedge or is_falling_wedge):
            return []

        resistance = peak_vals[-1]
        support = low_vals[-1]
        current_close = df["close"].iloc[-1]

        if is_rising_wedge:
            direction = "bearish"
            neckline = support
            confirmed = current_close < support
        else:
            direction = "bullish"
            neckline = resistance
            confirmed = current_close > resistance

        all_idx = peaks[-3:] + lows_idx[-3:]
        status = "confirmed" if confirmed else ("complete" if max(all_idx) == len(df) - 1 else "forming")

        return [{
            "pattern": "Rising Wedge" if is_rising_wedge else "Falling Wedge",
            "type": "breakout",
            "direction": direction,
            "status": status,
            "support": round(support, 2),
            "resistance": round(resistance, 2),
            "neckline": round(neckline, 2),
            "start_date": _bar_date(df, min(all_idx)),
            "end_date": _bar_date(df, max(all_idx)),
            "bars_formed": max(all_idx) - min(all_idx),
            "observations": [
                f"{'Rising' if is_rising_wedge else 'Falling'} wedge — both trendlines converging",
                f"Upper bound {resistance:,.2f}, lower bound {support:,.2f}",
            ],
        }]

    @staticmethod
    def detect_cup_and_handle(df: pd.DataFrame) -> list[dict]:
        """U-shaped cup followed by small handle (30–50% retracement), breakout above rim."""
        if len(df) < 30:
            return []

        n = len(df)
        # Cup: left rim in first third, bottom in middle, right rim in last third
        third = n // 3
        left_rim = df["high"].iloc[:third].max()
        left_rim_idx = df["high"].iloc[:third].idxmax()
        cup_bottom = df["low"].iloc[third: 2 * third].min()
        cup_bottom_idx = df["low"].iloc[third: 2 * third].idxmin()
        right_section = df["high"].iloc[2 * third:]
        right_rim = right_section.max()
        right_rim_idx = right_section.idxmax()

        # Rims should be within 5% of each other
        if abs(left_rim - right_rim) / max(left_rim, right_rim) > 0.05:
            return []

        # Cup depth: bottom at least 10% below rim
        avg_rim = (left_rim + right_rim) / 2
        if (avg_rim - cup_bottom) / avg_rim < 0.10:
            return []

        # Handle: small pullback after right rim
        handle_section = df.iloc[right_rim_idx:]
        if len(handle_section) < 3:
            handle_low = right_rim
        else:
            handle_low = handle_section["low"].min()

        cup_height = avg_rim - cup_bottom
        handle_retrace = (right_rim - handle_low) / cup_height if cup_height > 0 else 0

        # Handle retraces 10–60% of cup
        if not (0.10 <= handle_retrace <= 0.60):
            return []

        current_close = df["close"].iloc[-1]
        status = "confirmed" if current_close > avg_rim else "complete"

        return [{
            "pattern": "Cup and Handle",
            "type": "breakout",
            "direction": "bullish",
            "status": status,
            "support": round(cup_bottom, 2),
            "resistance": round(avg_rim, 2),
            "neckline": round(avg_rim, 2),
            "start_date": _bar_date(df, left_rim_idx if isinstance(left_rim_idx, int) else 0),
            "end_date": _bar_date(df, n - 1),
            "bars_formed": n,
            "observations": [
                f"Cup rim near {avg_rim:,.2f}, bottom at {cup_bottom:,.2f}",
                f"Handle retraced {handle_retrace * 100:.0f}% of cup",
            ],
        }]

    @staticmethod
    def detect_rounding_bottom(df: pd.DataFrame) -> list[dict]:
        """Gradual curved reversal — no sharp V; volume decreasing into bottom."""
        if len(df) < 20:
            return []

        n = len(df)
        third = n // 3

        left_avg = df["close"].iloc[:third].mean()
        mid_avg = df["close"].iloc[third: 2 * third].mean()
        right_avg = df["close"].iloc[2 * third:].mean()

        # Mid should be lowest (curved bottom)
        if not (mid_avg < left_avg and mid_avg < right_avg):
            return []

        # No sharp V: each third should be smoothly changing
        left_std = df["close"].iloc[:third].std()
        mid_std = df["close"].iloc[third: 2 * third].std()
        price_range = df["close"].max() - df["close"].min()
        if price_range <= 0:
            return []

        # Std within each section should be < 30% of total range (smooth curve)
        if left_std / price_range > 0.3 or mid_std / price_range > 0.3:
            return []

        # Volume: compare left half vs right half (decreasing into bottom = bullish)
        if "volume" in df.columns and df["volume"].sum() > 0:
            left_vol = df["volume"].iloc[:n // 2].mean()
            right_vol = df["volume"].iloc[n // 2:].mean()
            vol_note = "volume increasing on right side" if right_vol > left_vol else "volume decreasing"
        else:
            vol_note = ""

        rim = df["high"].max()
        bottom = df["low"].min()
        current_close = df["close"].iloc[-1]
        status = "confirmed" if current_close > rim else "forming"

        obs = [f"Gradual curved bottom from {left_avg:,.2f} to {mid_avg:,.2f} recovering to {right_avg:,.2f}"]
        if vol_note:
            obs.append(vol_note.capitalize())

        return [{
            "pattern": "Rounding Bottom",
            "type": "breakout",
            "direction": "bullish",
            "status": status,
            "support": round(bottom, 2),
            "resistance": round(rim, 2),
            "neckline": round(rim, 2),
            "start_date": _bar_date(df, 0),
            "end_date": _bar_date(df, n - 1),
            "bars_formed": n,
            "observations": obs,
        }]

"""
Reversal chart pattern detectors.

All detectors operate on a pandas DataFrame with columns:
  datetime, open, high, low, close, volume
and return a list of pattern dicts (empty if none found).
"""
from __future__ import annotations

import pandas as pd

_PEAK_SIMILARITY = 0.01    # peaks/troughs must be within 1% of each other
_SHOULDER_SIMILARITY = 0.02  # H&S shoulders within 2%
_VALLEY_DEPTH = 0.03       # valley must be at least 3% below peaks
_PEAK_HEIGHT = 0.03        # peak must be at least 3% above troughs


def _find_local_highs(df: pd.DataFrame, window: int = 3) -> list[int]:
    """Return indices of local highs (high > all neighbours within window)."""
    highs = []
    for i in range(window, len(df) - window):
        if df["high"].iloc[i] == df["high"].iloc[i - window: i + window + 1].max():
            highs.append(i)
    return highs


def _find_local_lows(df: pd.DataFrame, window: int = 3) -> list[int]:
    """Return indices of local lows (low < all neighbours within window)."""
    lows = []
    for i in range(window, len(df) - window):
        if df["low"].iloc[i] == df["low"].iloc[i - window: i + window + 1].min():
            lows.append(i)
    return lows


def _bar_date(df: pd.DataFrame, idx: int) -> str:
    val = df["datetime"].iloc[idx]
    return str(val)[:10]


class ReversalPatterns:

    @staticmethod
    def detect_double_top(df: pd.DataFrame) -> list[dict]:
        """Two peaks at similar price (within 1%), valley ≥3% below, neckline at valley."""
        if len(df) < 10:
            return []
        results = []
        peaks = _find_local_highs(df)
        if len(peaks) < 2:
            return []

        for i in range(len(peaks) - 1):
            for j in range(i + 1, len(peaks)):
                p1_idx, p2_idx = peaks[i], peaks[j]
                p1 = df["high"].iloc[p1_idx]
                p2 = df["high"].iloc[p2_idx]

                # Peaks must be within 1% of each other
                if abs(p1 - p2) / max(p1, p2) > _PEAK_SIMILARITY:
                    continue

                # Find valley low between the two peaks
                between = df["low"].iloc[p1_idx:p2_idx + 1]
                valley_low = between.min()
                avg_peak = (p1 + p2) / 2

                # Valley must be ≥3% below peaks
                if (avg_peak - valley_low) / avg_peak < _VALLEY_DEPTH:
                    continue

                neckline = valley_low
                current_close = df["close"].iloc[-1]
                if current_close < neckline:
                    status = "confirmed"
                elif p2_idx == peaks[-1]:
                    status = "complete"
                else:
                    status = "forming"

                results.append({
                    "pattern": "Double Top",
                    "type": "reversal",
                    "direction": "bearish",
                    "status": status,
                    "support": round(neckline, 2),
                    "resistance": round(avg_peak, 2),
                    "neckline": round(neckline, 2),
                    "start_date": _bar_date(df, p1_idx),
                    "end_date": _bar_date(df, p2_idx),
                    "bars_formed": p2_idx - p1_idx,
                    "observations": [
                        f"Two peaks near {avg_peak:,.2f}",
                        f"Neckline support at {neckline:,.2f}",
                    ],
                })
        return results

    @staticmethod
    def detect_double_bottom(df: pd.DataFrame) -> list[dict]:
        """Two troughs at similar price (within 1%), peak ≥3% above, neckline at peak."""
        if len(df) < 10:
            return []
        results = []
        troughs = _find_local_lows(df)
        if len(troughs) < 2:
            return []

        for i in range(len(troughs) - 1):
            for j in range(i + 1, len(troughs)):
                t1_idx, t2_idx = troughs[i], troughs[j]
                t1 = df["low"].iloc[t1_idx]
                t2 = df["low"].iloc[t2_idx]

                if abs(t1 - t2) / max(t1, t2) > _PEAK_SIMILARITY:
                    continue

                between = df["high"].iloc[t1_idx:t2_idx + 1]
                peak_high = between.max()
                avg_trough = (t1 + t2) / 2

                if (peak_high - avg_trough) / avg_trough < _PEAK_HEIGHT:
                    continue

                neckline = peak_high
                current_close = df["close"].iloc[-1]
                if current_close > neckline:
                    status = "confirmed"
                elif t2_idx == troughs[-1]:
                    status = "complete"
                else:
                    status = "forming"

                results.append({
                    "pattern": "Double Bottom",
                    "type": "reversal",
                    "direction": "bullish",
                    "status": status,
                    "support": round(avg_trough, 2),
                    "resistance": round(neckline, 2),
                    "neckline": round(neckline, 2),
                    "start_date": _bar_date(df, t1_idx),
                    "end_date": _bar_date(df, t2_idx),
                    "bars_formed": t2_idx - t1_idx,
                    "observations": [
                        f"Two troughs near {avg_trough:,.2f}",
                        f"Neckline resistance at {neckline:,.2f}",
                    ],
                })
        return results

    @staticmethod
    def detect_head_and_shoulders(df: pd.DataFrame) -> list[dict]:
        """Three peaks — middle (head) highest, shoulders within 2%, neckline at troughs."""
        if len(df) < 15:
            return []
        results = []
        peaks = _find_local_highs(df)
        if len(peaks) < 3:
            return []

        for i in range(len(peaks) - 2):
            ls_idx = peaks[i]
            h_idx  = peaks[i + 1]
            rs_idx = peaks[i + 2]

            ls = df["high"].iloc[ls_idx]
            head = df["high"].iloc[h_idx]
            rs = df["high"].iloc[rs_idx]

            # Head must be highest
            if not (head > ls and head > rs):
                continue

            # Shoulders within 2% of each other
            if abs(ls - rs) / max(ls, rs) > _SHOULDER_SIMILARITY:
                continue

            # Find neckline troughs between ls→head and head→rs
            left_trough = df["low"].iloc[ls_idx:h_idx + 1].min()
            right_trough = df["low"].iloc[h_idx:rs_idx + 1].min()
            neckline = (left_trough + right_trough) / 2

            current_close = df["close"].iloc[-1]
            if current_close < neckline:
                status = "confirmed"
            elif rs_idx == peaks[-1]:
                status = "complete"
            else:
                status = "forming"

            results.append({
                "pattern": "Head and Shoulders",
                "type": "reversal",
                "direction": "bearish",
                "status": status,
                "support": round(neckline, 2),
                "resistance": round(head, 2),
                "neckline": round(neckline, 2),
                "start_date": _bar_date(df, ls_idx),
                "end_date": _bar_date(df, rs_idx),
                "bars_formed": rs_idx - ls_idx,
                "observations": [
                    f"Head at {head:,.2f}, shoulders near {(ls + rs) / 2:,.2f}",
                    f"Neckline at {neckline:,.2f}",
                ],
            })
        return results

    @staticmethod
    def detect_inverse_head_and_shoulders(df: pd.DataFrame) -> list[dict]:
        """Three troughs — middle (head) lowest, shoulders within 2%, neckline at peaks."""
        if len(df) < 15:
            return []
        results = []
        troughs = _find_local_lows(df)
        if len(troughs) < 3:
            return []

        for i in range(len(troughs) - 2):
            ls_idx = troughs[i]
            h_idx  = troughs[i + 1]
            rs_idx = troughs[i + 2]

            ls = df["low"].iloc[ls_idx]
            head = df["low"].iloc[h_idx]
            rs = df["low"].iloc[rs_idx]

            # Head must be lowest
            if not (head < ls and head < rs):
                continue

            # Shoulders within 2% of each other
            if abs(ls - rs) / max(ls, rs) > _SHOULDER_SIMILARITY:
                continue

            left_peak = df["high"].iloc[ls_idx:h_idx + 1].max()
            right_peak = df["high"].iloc[h_idx:rs_idx + 1].max()
            neckline = (left_peak + right_peak) / 2

            current_close = df["close"].iloc[-1]
            if current_close > neckline:
                status = "confirmed"
            elif rs_idx == troughs[-1]:
                status = "complete"
            else:
                status = "forming"

            results.append({
                "pattern": "Inverse Head and Shoulders",
                "type": "reversal",
                "direction": "bullish",
                "status": status,
                "support": round(head, 2),
                "resistance": round(neckline, 2),
                "neckline": round(neckline, 2),
                "start_date": _bar_date(df, ls_idx),
                "end_date": _bar_date(df, rs_idx),
                "bars_formed": rs_idx - ls_idx,
                "observations": [
                    f"Head at {head:,.2f}, shoulders near {(ls + rs) / 2:,.2f}",
                    f"Neckline at {neckline:,.2f}",
                ],
            })
        return results

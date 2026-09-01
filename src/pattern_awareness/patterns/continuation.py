"""
Continuation chart pattern detectors.
"""
from __future__ import annotations

import pandas as pd

_FLAGPOLE_MIN_MOVE = 0.03   # flagpole must be ≥3% move
_FLAGPOLE_BARS = 5          # flagpole measured over 5 bars
_FLAG_MAX_BARS = 20         # consolidation window for flag/pennant


def _bar_date(df: pd.DataFrame, idx: int) -> str:
    return str(df["datetime"].iloc[idx])[:10]


class ContinuationPatterns:

    @staticmethod
    def detect_flag(df: pd.DataFrame) -> list[dict]:
        """Flagpole ≥3% in ≤5 bars followed by tight parallel-channel consolidation."""
        if len(df) < _FLAGPOLE_BARS + 5:
            return []
        results = []
        n = len(df)

        for pole_end in range(_FLAGPOLE_BARS, n - 4):
            pole_start = pole_end - _FLAGPOLE_BARS
            pole_open = df["close"].iloc[pole_start]
            pole_close = df["close"].iloc[pole_end]
            if pole_open <= 0:
                continue
            move = (pole_close - pole_open) / pole_open

            is_bull = move >= _FLAGPOLE_MIN_MOVE
            is_bear = move <= -_FLAGPOLE_MIN_MOVE
            if not (is_bull or is_bear):
                continue

            # Consolidation window: up to FLAG_MAX_BARS after pole
            cons_end = min(pole_end + _FLAG_MAX_BARS, n - 1)
            cons_df = df.iloc[pole_end:cons_end + 1]
            if len(cons_df) < 4:
                continue

            cons_high = cons_df["high"].max()
            cons_low = cons_df["low"].min()
            cons_range = cons_high - cons_low
            pole_size = abs(pole_close - pole_open)

            # Flag consolidation should be narrower than pole
            if cons_range >= pole_size * 0.6:
                continue

            # Check counter-trend drift in consolidation
            cons_start_close = cons_df["close"].iloc[0]
            cons_end_close = cons_df["close"].iloc[-1]
            drift = (cons_end_close - cons_start_close) / max(cons_start_close, 1e-9)

            if is_bull and drift > 0.01:
                continue  # bull flag should drift down or sideways
            if is_bear and drift < -0.01:
                continue  # bear flag should drift up or sideways

            direction = "bullish" if is_bull else "bearish"
            current_close = df["close"].iloc[-1]
            if (is_bull and current_close > cons_high) or (is_bear and current_close < cons_low):
                status = "confirmed"
            elif cons_end == n - 1:
                status = "complete"
            else:
                status = "forming"

            results.append({
                "pattern": "Bull Flag" if is_bull else "Bear Flag",
                "type": "continuation",
                "direction": direction,
                "status": status,
                "support": round(cons_low, 2),
                "resistance": round(cons_high, 2),
                "neckline": round(cons_high if is_bull else cons_low, 2),
                "start_date": _bar_date(df, pole_start),
                "end_date": _bar_date(df, cons_end),
                "bars_formed": cons_end - pole_start,
                "observations": [
                    f"Flagpole: {move * 100:+.1f}% move over {_FLAGPOLE_BARS} bars",
                    f"Consolidation range {cons_low:,.2f}–{cons_high:,.2f}",
                ],
            })
            break  # one flag per call is sufficient

        return results

    @staticmethod
    def detect_pennant(df: pd.DataFrame) -> list[dict]:
        """Flagpole followed by converging (triangular) consolidation with diminishing range."""
        if len(df) < _FLAGPOLE_BARS + 5:
            return []
        results = []
        n = len(df)

        for pole_end in range(_FLAGPOLE_BARS, n - 4):
            pole_start = pole_end - _FLAGPOLE_BARS
            pole_open = df["close"].iloc[pole_start]
            pole_close = df["close"].iloc[pole_end]
            if pole_open <= 0:
                continue
            move = (pole_close - pole_open) / pole_open

            is_bull = move >= _FLAGPOLE_MIN_MOVE
            is_bear = move <= -_FLAGPOLE_MIN_MOVE
            if not (is_bull or is_bear):
                continue

            cons_end = min(pole_end + _FLAG_MAX_BARS, n - 1)
            cons_df = df.iloc[pole_end:cons_end + 1].reset_index(drop=True)
            if len(cons_df) < 5:
                continue

            # Check convergence: range in first half > range in second half
            mid = len(cons_df) // 2
            first_range = cons_df["high"].iloc[:mid].max() - cons_df["low"].iloc[:mid].min()
            second_range = cons_df["high"].iloc[mid:].max() - cons_df["low"].iloc[mid:].min()

            if second_range >= first_range * 0.8:
                continue  # not converging enough

            apex_high = cons_df["high"].iloc[-1]
            apex_low = cons_df["low"].iloc[-1]
            current_close = df["close"].iloc[-1]

            if (is_bull and current_close > apex_high) or (is_bear and current_close < apex_low):
                status = "confirmed"
            elif cons_end == n - 1:
                status = "complete"
            else:
                status = "forming"

            direction = "bullish" if is_bull else "bearish"
            pole_size = abs(pole_close - pole_open)
            results.append({
                "pattern": "Pennant",
                "type": "continuation",
                "direction": direction,
                "status": status,
                "support": round(apex_low, 2),
                "resistance": round(apex_high, 2),
                "neckline": round(apex_high if is_bull else apex_low, 2),
                "start_date": _bar_date(df, pole_start),
                "end_date": _bar_date(df, cons_end),
                "bars_formed": cons_end - pole_start,
                "observations": [
                    f"Flagpole: {move * 100:+.1f}% move, converging consolidation",
                    f"Apex near {(apex_high + apex_low) / 2:,.2f}",
                ],
            })
            break

        return results

    @staticmethod
    def detect_rectangle(df: pd.DataFrame) -> list[dict]:
        """Price bouncing between horizontal S/R with ≥2 touches each side."""
        if len(df) < 10:
            return []

        # Use rolling windows to find flat-top / flat-bottom zones
        highs = df["high"].values
        lows = df["low"].values
        n = len(df)

        # Find resistance band (top ~2% zone with ≥2 touches)
        resistance = df["high"].max()
        band = resistance * 0.02
        res_touches = sum(1 for h in highs if h >= resistance - band)

        support = df["low"].min()
        sup_band = support * 0.02
        sup_touches = sum(1 for l in lows if l <= support + sup_band)

        if res_touches < 2 or sup_touches < 2:
            return []

        channel_width = resistance - support
        if channel_width / resistance < 0.02:
            return []  # too narrow to be meaningful

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
            "pattern": "Rectangle",
            "type": "continuation",
            "direction": direction,
            "status": status,
            "support": round(support, 2),
            "resistance": round(resistance, 2),
            "neckline": round(resistance if direction != "bearish" else support, 2),
            "start_date": _bar_date(df, 0),
            "end_date": _bar_date(df, n - 1),
            "bars_formed": n,
            "observations": [
                f"Resistance zone near {resistance:,.2f} ({res_touches} touches)",
                f"Support zone near {support:,.2f} ({sup_touches} touches)",
            ],
        }]

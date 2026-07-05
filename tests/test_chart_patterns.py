"""
Tests for Phase 5 — Chart Pattern Awareness.
All data is synthetic — no live API calls.
"""
from __future__ import annotations

import pandas as pd
import pytest

from src.pattern_awareness.patterns.reversal import ReversalPatterns
from src.pattern_awareness.patterns.continuation import ContinuationPatterns
from src.pattern_awareness.patterns.breakout import BreakoutPatterns
from src.pattern_awareness.detector import ChartPatternDetector


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row(dt, o, h, l, c, v=100_000):
    return {"datetime": dt, "open": o, "high": h, "low": l, "close": c, "volume": v}


def _df(*rows):
    return pd.DataFrame(rows)


def _dates(n, start="2026-01-01"):
    from datetime import date, timedelta
    d = date.fromisoformat(start)
    return [(d + timedelta(days=i)).isoformat() for i in range(n)]


# ---------------------------------------------------------------------------
# Reversal — Double Top
# ---------------------------------------------------------------------------

class TestDoubleTop:

    def _make(self):
        # Two peaks ~100, valley ~95, then close below neckline
        dates = _dates(20)
        rows = []
        prices = [
            90, 92, 95, 98, 100,  # rise to peak 1
            100, 97, 95, 95, 96,  # valley
            97, 99, 100, 100, 98, # rise to peak 2
            97, 95, 93, 91, 89,   # break below neckline
        ]
        for i, p in enumerate(prices):
            rows.append(_row(dates[i], p - 0.5, p + 0.5, p - 1, p))
        return pd.DataFrame(rows)

    def test_detects_double_top(self):
        df = self._make()
        results = ReversalPatterns.detect_double_top(df)
        assert any(r["pattern"] == "Double Top" for r in results)

    def test_double_top_fields(self):
        df = self._make()
        results = ReversalPatterns.detect_double_top(df)
        for r in results:
            assert r["type"] == "reversal"
            assert r["direction"] == "bearish"
            assert r["status"] in ("forming", "complete", "confirmed")
            assert r["neckline"] > 0
            assert r["support"] > 0
            assert r["resistance"] > 0
            assert r["bars_formed"] >= 0

    def test_empty_df_returns_empty(self):
        assert ReversalPatterns.detect_double_top(pd.DataFrame()) == []

    def test_insufficient_bars(self):
        df = _df(*[_row("2026-01-01", 100, 101, 99, 100)] * 5)
        assert ReversalPatterns.detect_double_top(df) == []


# ---------------------------------------------------------------------------
# Reversal — Double Bottom
# ---------------------------------------------------------------------------

class TestDoubleBottom:

    def _make(self):
        dates = _dates(20)
        rows = []
        prices = [
            110, 108, 105, 102, 100,   # fall to trough 1
            100, 102, 105, 105, 104,   # peak between
            103, 101, 100, 100, 101,   # trough 2
            103, 106, 109, 112, 115,   # break above neckline
        ]
        for i, p in enumerate(prices):
            rows.append(_row(dates[i], p - 0.5, p + 0.5, p - 1, p))
        return pd.DataFrame(rows)

    def test_detects_double_bottom(self):
        df = self._make()
        results = ReversalPatterns.detect_double_bottom(df)
        assert any(r["pattern"] == "Double Bottom" for r in results)

    def test_double_bottom_bullish(self):
        df = self._make()
        results = ReversalPatterns.detect_double_bottom(df)
        for r in results:
            assert r["direction"] == "bullish"
            assert r["type"] == "reversal"


# ---------------------------------------------------------------------------
# Reversal — Head and Shoulders
# ---------------------------------------------------------------------------

class TestHeadAndShoulders:

    def _make(self):
        # window=3: each peak must beat 3 bars on each side
        # LS at idx=3, head at idx=11, RS at idx=19 (8 bars apart)
        dates = _dates(30)
        hs_highs = [88,89,90,98,90,89,88,87,88,89,90,105,90,89,88,87,88,89,90,97,90,89,88,87,86,85,84,83,82,81]
        hs_lows  = [85,86,87,88,87,86,85,84,85,86,87, 88,87,86,85,84,85,86,87, 88,87,86,85,84,83,82,81,80,79,78]
        hs_c     = [86,87,88,95,88,87,86,85,86,87,88,100,88,87,86,85,86,87,88, 95,87,86,85,84,83,82,81,80,79,78]
        rows = [_row(dates[i], hs_c[i]-0.3, hs_highs[i], hs_lows[i], hs_c[i]) for i in range(30)]
        return pd.DataFrame(rows)

    def test_detects_hs(self):
        df = self._make()
        results = ReversalPatterns.detect_head_and_shoulders(df)
        assert any(r["pattern"] == "Head and Shoulders" for r in results)

    def test_hs_bearish(self):
        df = self._make()
        results = ReversalPatterns.detect_head_and_shoulders(df)
        for r in results:
            assert r["direction"] == "bearish"


# ---------------------------------------------------------------------------
# Reversal — Inverse Head and Shoulders
# ---------------------------------------------------------------------------

class TestInverseHeadAndShoulders:

    def _make(self):
        # window=3: each trough must be lower than 3 bars on each side
        # LS trough at idx=3 (102), head at idx=11 (95), RS trough at idx=19 (103)
        dates = _dates(30)
        ihs_lows  = [112,111,110,102,110,111,112,113,112,111,110, 95,110,111,112,113,112,111,110,103,110,111,112,113,114,115,116,117,118,119]
        ihs_highs = [115,114,113,112,113,114,115,116,115,114,113,112,113,114,115,116,115,114,113,112,113,114,115,116,117,118,119,120,121,122]
        ihs_c     = [113,112,111,105,111,112,113,114,113,112,111,100,111,112,113,114,113,112,111,106,111,112,113,114,115,116,117,118,119,120]
        rows = [_row(dates[i], ihs_c[i]-0.3, ihs_highs[i], ihs_lows[i], ihs_c[i]) for i in range(30)]
        return pd.DataFrame(rows)

    def test_detects_ihs(self):
        df = self._make()
        results = ReversalPatterns.detect_inverse_head_and_shoulders(df)
        assert any(r["pattern"] == "Inverse Head and Shoulders" for r in results)

    def test_ihs_bullish(self):
        df = self._make()
        results = ReversalPatterns.detect_inverse_head_and_shoulders(df)
        for r in results:
            assert r["direction"] == "bullish"


# ---------------------------------------------------------------------------
# Continuation — Flag
# ---------------------------------------------------------------------------

class TestFlag:

    def _make_bull_flag(self):
        dates = _dates(20)
        rows = []
        # Flagpole: 5 bars, strong rise ~6% (pole_size=6)
        pole = [100, 102, 104, 105, 106]
        # Tight consolidation: range must be < 60% of pole_size=6 → range < 3.6
        # Use range of ~1.5 (104.5 to 106.0), drift slightly down
        cons = [105.8, 105.6, 105.4, 105.3, 105.2, 105.1, 105.0, 104.9, 104.8, 104.7,
                104.6, 104.5, 104.4, 104.3, 104.2]
        for i, p in enumerate(pole + cons):
            rows.append(_row(dates[i], p - 0.1, p + 0.1, p - 0.2, p))
        return pd.DataFrame(rows)

    def test_detects_bull_flag(self):
        df = self._make_bull_flag()
        results = ContinuationPatterns.detect_flag(df)
        assert any("Flag" in r["pattern"] for r in results)

    def test_flag_fields(self):
        df = self._make_bull_flag()
        results = ContinuationPatterns.detect_flag(df)
        for r in results:
            assert r["type"] == "continuation"
            assert r["status"] in ("forming", "complete", "confirmed")
            assert r["support"] > 0
            assert r["resistance"] > 0


# ---------------------------------------------------------------------------
# Breakout — Ascending Triangle
# ---------------------------------------------------------------------------

class TestAscendingTriangle:

    def _make(self):
        dates = _dates(20)
        # Flat resistance at 100, rising lows
        rows = []
        highs =  [100, 98, 100, 97, 100, 98, 100, 99, 100, 99,
                  100, 99, 100, 99, 100, 99, 100, 99, 100, 101]
        lows  =  [ 95, 94,  95, 95,  96, 95,  96, 96,  97, 96,
                    97, 97,  98, 97,  98, 98,  99, 98,  99,  98]
        closes = [ 97, 96,  98, 96,  98, 97,  99, 98,  99, 98,
                   99, 98,  99, 98,  99, 99, 100, 99, 100, 101]
        for i in range(20):
            rows.append(_row(dates[i], closes[i] - 0.5, highs[i], lows[i], closes[i]))
        return pd.DataFrame(rows)

    def test_detects_ascending_triangle(self):
        df = self._make()
        results = BreakoutPatterns.detect_ascending_triangle(df)
        assert any(r["pattern"] == "Ascending Triangle" for r in results)

    def test_ascending_triangle_bullish(self):
        df = self._make()
        results = BreakoutPatterns.detect_ascending_triangle(df)
        for r in results:
            assert r["direction"] == "bullish"
            assert r["type"] == "breakout"


# ---------------------------------------------------------------------------
# Breakout — Descending Triangle
# ---------------------------------------------------------------------------

class TestDescendingTriangle:

    def _make(self):
        dates = _dates(20)
        rows = []
        highs =  [105, 103, 104, 102, 103, 101, 102, 100, 101, 100,
                  100,  99, 100,  99,  99,  98,  99,  98,  98,  97]
        lows  =  [ 99,  99,  99,  99,  99,  99,  99,  99,  99,  99,
                    99,  99,  99,  99,  99,  99,  99,  99,  99,  98]
        closes = [103, 101, 102, 101, 101, 100, 101, 100, 100,  99,
                   99,  99,  99,  99,  99,  99,  99,  99,  99,  98]
        for i in range(20):
            rows.append(_row(dates[i], closes[i], highs[i], lows[i], closes[i]))
        return pd.DataFrame(rows)

    def test_detects_descending_triangle(self):
        df = self._make()
        results = BreakoutPatterns.detect_descending_triangle(df)
        assert any(r["pattern"] == "Descending Triangle" for r in results)

    def test_descending_triangle_bearish(self):
        df = self._make()
        results = BreakoutPatterns.detect_descending_triangle(df)
        for r in results:
            assert r["direction"] == "bearish"
            assert r["type"] == "breakout"


# ---------------------------------------------------------------------------
# Breakout — Symmetrical Triangle
# ---------------------------------------------------------------------------

class TestSymmetricalTriangle:

    def _make(self):
        # Need clear local peaks and troughs with window=3 separation
        # Falling highs: 110, 106, 102, 98 (spaced 4 bars apart)
        # Rising lows:    90,  93,  96, 99
        dates = _dates(28)
        rows = []
        # idx: 0  1   2   3   4   5   6   7   8   9  10  11  12  13  14  15  16  17  18  19  20  21  22  23  24  25  26  27
        highs= [110,106,104,106,108,104,102,104,106,102,100,102,104,100, 98,100,102, 98, 96, 98,100, 96, 94, 96, 98, 96, 95,102]
        lows = [ 90, 88, 88, 90, 92, 90, 88, 90, 92, 90, 88, 90, 92, 91, 90, 91, 93, 91, 90, 92, 94, 92, 91, 93, 95, 94, 93, 95]
        closes=[100, 98,  96, 98,100, 97, 96, 97, 99, 96, 95, 96, 98, 96, 94, 96, 98, 95, 93, 95, 97, 94, 93, 95, 97, 95, 94, 99]
        for i in range(28):
            rows.append(_row(dates[i], closes[i], highs[i], lows[i], closes[i]))
        return pd.DataFrame(rows)

    def test_detects_symmetrical_triangle(self):
        df = self._make()
        results = BreakoutPatterns.detect_symmetrical_triangle(df)
        assert any(r["pattern"] == "Symmetrical Triangle" for r in results)

    def test_symmetrical_triangle_fields(self):
        df = self._make()
        results = BreakoutPatterns.detect_symmetrical_triangle(df)
        for r in results:
            assert r["type"] == "breakout"
            assert r["direction"] in ("bullish", "bearish", "neutral")


# ---------------------------------------------------------------------------
# Breakout — Wedge
# ---------------------------------------------------------------------------

class TestWedge:

    def _make_rising_wedge(self):
        # Peaks at even multiples of 4 (idx 4,8,12,16,20,24), troughs between
        # Lows rise faster than highs → converging = rising wedge
        dates = _dates(28)
        highs = [102,100,100,100,103,101,101,101,104,102,102,102,105,103,103,103,
                 106,104,104,104,107,105,105,105,108,106,106,106]
        lows  = [100, 98, 97, 98,101, 99, 99, 99,102,101,100,101,103,102,102,102,
                 105,103,104,103,106,104,105,104,107,106,106,106]
        c     = [101, 99, 98, 99,102,100, 99,100,103,101,101,101,104,102,102,102,
                 105,103,104,103,106,104,105,104,107,105,106,106]
        rows = [_row(dates[i], c[i]-0.2, highs[i], lows[i], c[i]) for i in range(28)]
        return pd.DataFrame(rows)

    def test_detects_rising_wedge(self):
        df = self._make_rising_wedge()
        results = BreakoutPatterns.detect_wedge(df)
        assert any(r["pattern"] == "Rising Wedge" for r in results)

    def test_rising_wedge_bearish(self):
        df = self._make_rising_wedge()
        results = BreakoutPatterns.detect_wedge(df)
        for r in results:
            if r["pattern"] == "Rising Wedge":
                assert r["direction"] == "bearish"


# ---------------------------------------------------------------------------
# Breakout — Cup and Handle
# ---------------------------------------------------------------------------

class TestCupAndHandle:

    def _make(self):
        import math
        dates = _dates(40)
        rows = []
        # Cup: left rim ~100, bottom ~85 at midpoint, right rim ~100
        # Handle: slight pullback after rim
        for i in range(40):
            if i < 10:
                # Left rim decline
                p = 100 - i * 1.5
            elif i < 20:
                # Rounded bottom
                p = 85 + math.sin((i - 10) / 10 * math.pi) * 5
            elif i < 30:
                # Right rim rise
                p = 85 + (i - 20) * 1.5
            else:
                # Handle: small pullback
                p = 100 - (i - 30) * 0.5
            rows.append(_row(dates[i], p - 0.5, p + 1, p - 1, p))
        return pd.DataFrame(rows)

    def test_detects_cup_and_handle(self):
        df = self._make()
        results = BreakoutPatterns.detect_cup_and_handle(df)
        assert any(r["pattern"] == "Cup and Handle" for r in results)

    def test_cup_and_handle_bullish(self):
        df = self._make()
        results = BreakoutPatterns.detect_cup_and_handle(df)
        for r in results:
            assert r["direction"] == "bullish"


# ---------------------------------------------------------------------------
# Breakout — Rounding Bottom
# ---------------------------------------------------------------------------

class TestRoundingBottom:

    def _make(self):
        import math
        dates = _dates(30)
        rows = []
        for i in range(30):
            # Inverted cosine: starts high, dips in middle, recovers
            # cos(0)=1, cos(pi)=-1 → 100 - 10*cos gives 90 at start, 110 at end
            # We want: high at start, low in middle, high at end
            # Use: p = 100 + 10*cos(i/30 * 2*pi - pi) → starts at 90, dips to 110 — wrong
            # Correct: start=110, mid=90, end=110 → p = 100 + 10*cos(i/(n-1)*2*pi)
            n = 30
            p = 100 + 10 * math.cos(i / (n - 1) * 2 * math.pi)
            rows.append(_row(dates[i], p - 0.3, p + 0.5, p - 0.5, p, v=100_000 - i * 1000))
        return pd.DataFrame(rows)

    def test_detects_rounding_bottom(self):
        df = self._make()
        results = BreakoutPatterns.detect_rounding_bottom(df)
        assert any(r["pattern"] == "Rounding Bottom" for r in results)

    def test_rounding_bottom_bullish(self):
        df = self._make()
        results = BreakoutPatterns.detect_rounding_bottom(df)
        for r in results:
            assert r["direction"] == "bullish"


# ---------------------------------------------------------------------------
# ChartPatternDetector (orchestrator)
# ---------------------------------------------------------------------------

class TestChartPatternDetector:

    def setup_method(self):
        self.det = ChartPatternDetector()

    def test_empty_df_returns_empty(self):
        assert self.det.detect_all(pd.DataFrame()) == []

    def test_insufficient_bars_returns_empty(self):
        rows = [_row("2026-01-01", 100, 101, 99, 100)] * 5
        df = pd.DataFrame(rows)
        assert self.det.detect_all(df, min_bars=10) == []

    def test_returns_list(self):
        dates = _dates(50)
        rows = []
        for i, d in enumerate(dates):
            p = 100 + (i % 5) - 2
            rows.append(_row(d, p - 0.5, p + 0.5, p - 0.5, p))
        df = pd.DataFrame(rows)
        result = self.det.detect_all(df)
        assert isinstance(result, list)

    def test_pattern_fields_present(self):
        dates = _dates(50)
        rows = []
        for i, d in enumerate(dates):
            p = 100 + (i % 5) - 2
            rows.append(_row(d, p - 0.5, p + 0.5, p - 0.5, p))
        df = pd.DataFrame(rows)
        patterns = self.det.detect_all(df)
        for p in patterns:
            assert "pattern" in p
            assert "type" in p
            assert "direction" in p
            assert "status" in p
            assert "support" in p
            assert "resistance" in p
            assert "neckline" in p
            assert "start_date" in p
            assert "end_date" in p
            assert "bars_formed" in p
            assert "observations" in p

    def test_status_values_valid(self):
        dates = _dates(60)
        rows = []
        for i, d in enumerate(dates):
            p = 100 + (i % 8) - 4
            rows.append(_row(d, p - 0.3, p + 0.5, p - 0.5, p))
        df = pd.DataFrame(rows)
        patterns = self.det.detect_all(df)
        for p in patterns:
            assert p["status"] in ("forming", "complete", "confirmed")

    def test_direction_values_valid(self):
        dates = _dates(50)
        rows = []
        for i, d in enumerate(dates):
            p = 100 + (i % 6) - 3
            rows.append(_row(d, p - 0.3, p + 0.5, p - 0.5, p))
        df = pd.DataFrame(rows)
        patterns = self.det.detect_all(df)
        for p in patterns:
            assert p["direction"] in ("bullish", "bearish", "neutral")

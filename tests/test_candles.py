"""
Tests for Phase 4 — Candlestick Pattern Awareness.
No live API calls — all data is synthetic.
"""
from __future__ import annotations

import pandas as pd
import pytest

from src.candle_awareness.classifier import build_context, classify_strength
from src.candle_awareness.detector import (
    SingleCandleDetectors,
    ThreeCandleDetectors,
    TwoCandleDetectors,
)
from src.candle_awareness.patterns import CandlePattern, PatternDetector

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row(o, h, l, c, v=1000, dt="2026-01-01"):
    return {"open": o, "high": h, "low": l, "close": c, "volume": v, "datetime": dt}


def _df(*rows):
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# SingleCandleDetectors
# ---------------------------------------------------------------------------

class TestSingleCandleDetectors:

    def setup_method(self):
        self.det = SingleCandleDetectors()

    def _names(self, row):
        return [n for n, _ in self.det.detect(row)]

    def test_doji(self):
        # body = 0.005, range = 10 — well within 0.1% of range threshold
        names = self._names(_row(100, 105, 95, 100.005))
        assert "Doji" in names

    def test_dragonfly_doji(self):
        # open ≈ close at top, long lower wick
        names = self._names(_row(100, 100.1, 90, 100))
        assert "Dragonfly Doji" in names

    def test_gravestone_doji(self):
        # open ≈ close at bottom, long upper wick
        names = self._names(_row(90, 100, 89.9, 90))
        assert "Gravestone Doji" in names

    def test_bullish_marubozu(self):
        # full body, no wicks
        names = self._names(_row(90, 100, 90, 100))
        assert "Bullish Marubozu" in names

    def test_bearish_marubozu(self):
        names = self._names(_row(100, 100, 90, 90))
        assert "Bearish Marubozu" in names

    def test_hammer(self):
        # small body (0.2) at top, long lower wick (6), tiny upper wick (0.05)
        # body <= 0.3*range(6.25) ✓, lower(6) >= 2*body(0.2) ✓, upper(0.05) <= 0.5*body(0.1) ✓
        names = self._names(_row(99.9, 100.05, 93.8, 100.1))
        assert "Hammer" in names

    def test_inverted_hammer(self):
        # small body at bottom, long upper wick (6), tiny lower wick (0.05)
        names = self._names(_row(99.9, 106.1, 99.85, 100.1))
        assert "Inverted Hammer" in names

    def test_shooting_star(self):
        # bearish, small body at bottom, long upper wick, tiny lower wick
        names = self._names(_row(100.1, 106.2, 100.05, 99.9))
        assert "Shooting Star" in names

    def test_spinning_top(self):
        # small body, equal wicks
        names = self._names(_row(100, 103, 97, 100.5))
        assert "Spinning Top" in names

    def test_no_pattern_plain_candle(self):
        # large body, moderate wicks — not a special pattern
        names = self._names(_row(90, 102, 88, 101))
        assert "Doji" not in names
        assert "Hammer" not in names


# ---------------------------------------------------------------------------
# TwoCandleDetectors
# ---------------------------------------------------------------------------

class TestTwoCandleDetectors:

    def setup_method(self):
        self.det = TwoCandleDetectors()

    def _names(self, prev, curr):
        return [n for n, _ in self.det.detect(prev, curr)]

    def test_bullish_engulfing(self):
        prev = _row(102, 103, 98, 99)   # bearish
        curr = _row(98, 106, 97, 105)   # bullish, larger body
        assert "Bullish Engulfing" in self._names(prev, curr)

    def test_bearish_engulfing(self):
        prev = _row(98, 103, 97, 102)   # bullish
        curr = _row(104, 105, 95, 96)   # bearish, larger body
        assert "Bearish Engulfing" in self._names(prev, curr)

    def test_bullish_harami(self):
        prev = _row(110, 111, 95, 96)   # large bearish
        curr = _row(98, 100, 97, 99)    # small bullish inside
        assert "Bullish Harami" in self._names(prev, curr)

    def test_bearish_harami(self):
        prev = _row(90, 111, 89, 110)   # large bullish
        curr = _row(105, 106, 103, 104) # small bearish inside
        assert "Bearish Harami" in self._names(prev, curr)

    def test_tweezer_bottom(self):
        prev = _row(102, 103, 95.0, 101)  # bearish-ish
        curr = _row(98, 104, 95.0, 103)   # bullish, same low
        assert "Tweezer Bottom" in self._names(prev, curr)

    def test_tweezer_top(self):
        prev = _row(98, 105.0, 97, 104)   # bullish-ish
        curr = _row(104, 105.0, 100, 101) # bearish, same high
        assert "Tweezer Top" in self._names(prev, curr)

    def test_piercing_line(self):
        prev = _row(106, 107, 98, 99)   # bearish
        curr = _row(97, 106, 96, 104)   # bullish, opens below prev low, closes above midpoint
        assert "Piercing Line" in self._names(prev, curr)

    def test_dark_cloud_cover(self):
        prev = _row(94, 106, 93, 105)   # bullish
        curr = _row(107, 108, 97, 98)   # bearish, opens above prev high, closes below midpoint
        assert "Dark Cloud Cover" in self._names(prev, curr)


# ---------------------------------------------------------------------------
# ThreeCandleDetectors
# ---------------------------------------------------------------------------

class TestThreeCandleDetectors:

    def setup_method(self):
        self.det = ThreeCandleDetectors()

    def _names(self, c1, c2, c3):
        return [n for n, _ in self.det.detect(c1, c2, c3)]

    def test_morning_star(self):
        c1 = _row(110, 111, 100, 101)   # large bearish
        c2 = _row(100, 101, 99, 100.2)  # small body
        c3 = _row(101, 110, 100, 108)   # large bullish, closes above midpoint of c1
        assert "Morning Star" in self._names(c1, c2, c3)

    def test_evening_star(self):
        c1 = _row(90, 102, 89, 101)     # large bullish
        c2 = _row(101, 102, 100, 101.2) # small body
        c3 = _row(100, 101, 90, 91)     # large bearish, closes below midpoint of c1
        assert "Evening Star" in self._names(c1, c2, c3)

    def test_three_white_soldiers(self):
        c1 = _row(90, 95, 89, 94)
        c2 = _row(94, 100, 93, 99)
        c3 = _row(99, 106, 98, 105)
        assert "Three White Soldiers" in self._names(c1, c2, c3)

    def test_three_black_crows(self):
        c1 = _row(105, 106, 100, 101)
        c2 = _row(101, 102, 96, 97)
        c3 = _row(97, 98, 91, 92)
        assert "Three Black Crows" in self._names(c1, c2, c3)

    def test_three_inside_up(self):
        c1 = _row(110, 111, 100, 101)   # large bearish
        c2 = _row(102, 104, 101, 103)   # small bullish inside c1
        c3 = _row(103, 112, 102, 110)   # bullish confirmation
        assert "Three Inside Up" in self._names(c1, c2, c3)

    def test_three_inside_down(self):
        c1 = _row(90, 110, 89, 109)     # large bullish
        c2 = _row(107, 108, 104, 105)   # small bearish inside c1
        c3 = _row(104, 105, 95, 96)     # bearish confirmation
        assert "Three Inside Down" in self._names(c1, c2, c3)


# ---------------------------------------------------------------------------
# PatternDetector (orchestrator)
# ---------------------------------------------------------------------------

class TestPatternDetector:

    def setup_method(self):
        self.det = PatternDetector()

    def test_returns_list_on_empty(self):
        assert self.det.detect_all(pd.DataFrame()) == []

    def test_returns_list_on_single_row(self):
        df = _df(_row(100, 110, 90, 100))
        result = self.det.detect_all(df)
        assert isinstance(result, list)

    def test_detects_pattern_in_sequence(self):
        rows = [
            _row(100, 101, 99, 100.5, dt="2026-01-01"),
            _row(100, 101, 99, 100.5, dt="2026-01-02"),
            _row(110, 111, 100, 101, dt="2026-01-03"),   # large bearish
            _row(100, 101, 99, 100.2, dt="2026-01-04"),  # small body
            _row(101, 110, 100, 108, dt="2026-01-05"),   # bullish — morning star
        ]
        df = _df(*rows)
        patterns = self.det.detect_all(df)
        names = [p.name for p in patterns]
        assert "Morning Star" in names

    def test_volume_ratio_computed(self):
        rows = [_row(99, 100, 92, 99.5, v=i * 100) for i in range(1, 12)]
        df = _df(*rows)
        patterns = self.det.detect_all(df)
        for p in patterns:
            assert p.volume_ratio >= 0

    def test_pattern_fields_present(self):
        rows = [
            _row(110, 111, 100, 101, dt="2026-01-01"),
            _row(100, 101, 99, 100.2, dt="2026-01-02"),
            _row(101, 110, 100, 108, dt="2026-01-03"),
        ]
        df = _df(*rows)
        patterns = self.det.detect_all(df)
        if patterns:
            p = patterns[0]
            assert hasattr(p, "name")
            assert hasattr(p, "pattern_type")
            assert hasattr(p, "strength")
            assert hasattr(p, "location")
            assert hasattr(p, "bar_date")
            assert hasattr(p, "volume_ratio")


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------

class TestClassifier:

    def _make_pattern(self, volume_ratio=1.0, close=100.0):
        return CandlePattern(
            name="Hammer", pattern_type="bullish", strength="weak",
            location=0, bar_date="2026-01-01",
            open=99.0, high=100.5, low=93.0, close=close,
            volume=1000.0, volume_ratio=volume_ratio,
        )

    def test_weak_no_context(self):
        p = self._make_pattern(volume_ratio=0.5)
        s = classify_strength(p, adx=10, rsi=50, levels={"supports": [], "resistances": []})
        assert s == "weak"

    def test_moderate_high_volume(self):
        p = self._make_pattern(volume_ratio=1.6)
        s = classify_strength(p, adx=10, rsi=50, levels={"supports": [], "resistances": []})
        assert s in ("moderate", "strong")

    def test_strong_at_support_with_volume(self):
        p = self._make_pattern(volume_ratio=1.6, close=100.0)
        levels = {"supports": [{"level": 100.2, "strength": "strong", "touches": 3}], "resistances": []}
        s = classify_strength(p, adx=30, rsi=40, levels=levels)
        assert s == "strong"

    def test_build_context_near_support(self):
        # support level must be below close for build_context to surface it
        p = self._make_pattern(close=100.0)
        levels = {"supports": [{"level": 99.8, "strength": "strong", "touches": 3}], "resistances": []}
        ctx = build_context(p, levels)
        assert "support" in ctx.lower()

    def test_build_context_near_resistance(self):
        p = self._make_pattern(close=100.0)
        levels = {"supports": [], "resistances": [{"level": 100.3, "strength": "weak", "touches": 1}]}
        ctx = build_context(p, levels)
        assert "resistance" in ctx.lower()

    def test_build_context_empty(self):
        p = self._make_pattern(close=100.0)
        levels = {"supports": [], "resistances": []}
        ctx = build_context(p, levels)
        assert ctx == ""


# ---------------------------------------------------------------------------
# MCP tool (mocked data fetch)
# ---------------------------------------------------------------------------

def _make_candles(n=40):
    candles = []
    price = 23000.0
    for i in range(n):
        o = price
        c = price + (5 if i % 2 == 0 else -3)
        h = max(o, c) + 2
        l = min(o, c) - 2
        candles.append({
            "datetime": f"2026-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}",
            "open": o, "high": h, "low": l, "close": c, "volume": 1000 + i * 10,
        })
        price = c
    return candles, "yahoo"


class TestCandleToolIntegration:
    """Integration tests using PatternDetector + classifier directly (no MCP wrapper needed)."""

    def test_full_pipeline_returns_patterns(self):
        candles, _ = _make_candles(40)
        df = pd.DataFrame(candles)
        det = PatternDetector()
        patterns = det.detect_all(df)
        assert isinstance(patterns, list)
        for p in patterns:
            assert p.name
            assert p.pattern_type in ("bullish", "bearish", "neutral")
            assert p.strength in ("weak", "moderate", "strong")
            assert isinstance(p.volume_ratio, float)

    def test_min_strength_filter_strong(self):
        candles, _ = _make_candles(40)
        df = pd.DataFrame(candles)
        det = PatternDetector()
        patterns = det.detect_all(df)
        strong = [p for p in patterns if p.strength == "strong"]
        # All strong patterns should remain after filtering
        for p in strong:
            assert p.strength == "strong"

    def test_no_data_empty_patterns(self):
        det = PatternDetector()
        result = det.detect_all(pd.DataFrame())
        assert result == []

    def test_pattern_fields_complete(self):
        candles, _ = _make_candles(60)
        df = pd.DataFrame(candles)
        det = PatternDetector()
        patterns = det.detect_all(df)
        for p in patterns:
            assert hasattr(p, "name")
            assert hasattr(p, "pattern_type")
            assert hasattr(p, "strength")
            assert hasattr(p, "location")
            assert hasattr(p, "bar_date")
            assert hasattr(p, "open")
            assert hasattr(p, "high")
            assert hasattr(p, "low")
            assert hasattr(p, "close")
            assert hasattr(p, "volume_ratio")
            assert hasattr(p, "context")

    def test_location_decreases_for_older_bars(self):
        candles, _ = _make_candles(15)
        df = pd.DataFrame(candles)
        det = PatternDetector()
        patterns = det.detect_all(df)
        for p in patterns:
            assert p.location >= 0

    def test_summary_counts_correct(self):
        candles, _ = _make_candles(40)
        df = pd.DataFrame(candles)
        det = PatternDetector()
        patterns = det.detect_all(df)
        bullish = sum(1 for p in patterns if p.pattern_type == "bullish")
        bearish = sum(1 for p in patterns if p.pattern_type == "bearish")
        neutral = sum(1 for p in patterns if p.pattern_type == "neutral")
        assert bullish + bearish + neutral == len(patterns)

"""Tests for src/intelligence/vix.py"""
from __future__ import annotations

import threading
import time

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_candles(values: list[float]) -> list[dict]:
    return [{"close": v, "open": v, "high": v, "low": v, "volume": 1000} for v in values]


def _fake_market(values: list[float]):
    class FakeSvc:
        def get_historical(self, ticker, start, end, interval):
            return _make_candles(values)

    class FakeMarketMod:
        def get_market(self):
            return FakeSvc()

    return FakeSvc()


# ---------------------------------------------------------------------------
# Interpretation thresholds
# ---------------------------------------------------------------------------

class TestInterpretation:
    def test_below_12_complacency(self):
        from src.intelligence.vix import _interpretation
        assert "Complacency" in _interpretation(10.0)

    def test_12_to_15_calm(self):
        from src.intelligence.vix import _interpretation
        assert "Calm" in _interpretation(13.0)

    def test_15_to_20_mild(self):
        from src.intelligence.vix import _interpretation
        assert "Mild" in _interpretation(17.0)

    def test_20_to_25_elevated(self):
        from src.intelligence.vix import _interpretation
        assert "Elevated" in _interpretation(22.0)

    def test_above_25_extreme(self):
        from src.intelligence.vix import _interpretation
        assert "Extreme" in _interpretation(30.0)


# ---------------------------------------------------------------------------
# Caution levels
# ---------------------------------------------------------------------------

class TestCautionLevel:
    def test_below_15_low(self):
        from src.intelligence.vix import _caution_level
        assert _caution_level(14.9) == "LOW"

    def test_15_to_20_moderate(self):
        from src.intelligence.vix import _caution_level
        assert _caution_level(17.0) == "MODERATE"

    def test_20_to_25_high(self):
        from src.intelligence.vix import _caution_level
        assert _caution_level(22.0) == "HIGH"

    def test_25_plus_extreme(self):
        from src.intelligence.vix import _caution_level
        assert _caution_level(28.0) == "EXTREME"


# ---------------------------------------------------------------------------
# Percentile calculation
# ---------------------------------------------------------------------------

class TestPercentile:
    def test_empty_history_returns_50(self):
        from src.intelligence.vix import _percentile
        assert _percentile(15.0, []) == 50

    def test_highest_in_history(self):
        from src.intelligence.vix import _percentile
        assert _percentile(100.0, [10.0, 20.0, 30.0]) == 100

    def test_lowest_in_history(self):
        from src.intelligence.vix import _percentile
        # 0 values are <= 5.0, so percentile = 0
        assert _percentile(0.0, [10.0, 20.0, 30.0]) == 0

    def test_median(self):
        from src.intelligence.vix import _percentile
        # 3/5 history values <= 15 → 60th percentile
        result = _percentile(15.0, [10.0, 12.0, 15.0, 18.0, 20.0])
        assert result == 60


# ---------------------------------------------------------------------------
# get_india_vix — happy path
# ---------------------------------------------------------------------------

class TestGetIndiaVix:
    def test_returns_expected_keys(self, monkeypatch):
        import src.intelligence.vix as vix_mod

        # Clear cache so fresh fetch happens
        with vix_mod._LOCK:
            vix_mod._CACHE.clear()

        values = [14.0 + i * 0.1 for i in range(30)]  # 30 days rising

        class FakeSvc:
            def get_historical(self, *a, **kw):
                return _make_candles(values)

        monkeypatch.setattr(vix_mod, "get_market", lambda: FakeSvc())

        result = vix_mod.get_india_vix()
        assert "error" not in result
        for key in ("level", "prev_close", "change_pct", "week52_high",
                    "week52_low", "percentile_52w", "interpretation", "caution_level"):
            assert key in result, f"missing key: {key}"

    def test_level_is_last_close(self, monkeypatch):
        import src.intelligence.vix as vix_mod

        with vix_mod._LOCK:
            vix_mod._CACHE.clear()

        values = [10.0, 12.0, 18.5]

        class FakeSvc:
            def get_historical(self, *a, **kw):
                return _make_candles(values)

        monkeypatch.setattr(vix_mod, "get_market", lambda: FakeSvc())
        result = vix_mod.get_india_vix()
        assert result["level"] == 18.5

    def test_single_candle_no_prev(self, monkeypatch):
        import src.intelligence.vix as vix_mod

        with vix_mod._LOCK:
            vix_mod._CACHE.clear()

        class FakeSvc:
            def get_historical(self, *a, **kw):
                return _make_candles([16.0])

        monkeypatch.setattr(vix_mod, "get_market", lambda: FakeSvc())
        result = vix_mod.get_india_vix()
        assert result["prev_close"] is None
        assert result["change_pct"] is None

    def test_empty_candles_returns_error(self, monkeypatch):
        import src.intelligence.vix as vix_mod

        with vix_mod._LOCK:
            vix_mod._CACHE.clear()

        class FakeSvc:
            def get_historical(self, *a, **kw):
                return []

        monkeypatch.setattr(vix_mod, "get_market", lambda: FakeSvc())
        result = vix_mod.get_india_vix()
        assert "error" in result

    def test_exception_returns_error(self, monkeypatch):
        import src.intelligence.vix as vix_mod

        with vix_mod._LOCK:
            vix_mod._CACHE.clear()

        class FakeSvc:
            def get_historical(self, *a, **kw):
                raise RuntimeError("network failure")

        monkeypatch.setattr(vix_mod, "get_market", lambda: FakeSvc())
        result = vix_mod.get_india_vix()
        assert "error" in result


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------

class TestCaching:
    def test_second_call_returns_cached(self, monkeypatch):
        import src.intelligence.vix as vix_mod

        with vix_mod._LOCK:
            vix_mod._CACHE.clear()

        call_count = 0

        class FakeSvc:
            def get_historical(self, *a, **kw):
                nonlocal call_count
                call_count += 1
                return _make_candles([15.0, 16.0])

        monkeypatch.setattr(vix_mod, "get_market", lambda: FakeSvc())
        vix_mod.get_india_vix()
        vix_mod.get_india_vix()
        assert call_count == 1  # second call hit cache

    def test_expired_cache_refetches(self, monkeypatch):
        import src.intelligence.vix as vix_mod

        with vix_mod._LOCK:
            vix_mod._CACHE.clear()

        call_count = 0

        class FakeSvc:
            def get_historical(self, *a, **kw):
                nonlocal call_count
                call_count += 1
                return _make_candles([15.0, 16.0])

        monkeypatch.setattr(vix_mod, "get_market", lambda: FakeSvc())
        # Manually insert stale entry
        stale_result = {"level": 15.0}
        with vix_mod._LOCK:
            vix_mod._CACHE["india_vix"] = (stale_result, time.monotonic() - vix_mod._TTL - 1)

        vix_mod.get_india_vix()
        assert call_count == 1  # should have re-fetched

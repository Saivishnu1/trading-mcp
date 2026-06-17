"""Tests for src/intelligence/global_pulse.py"""
from __future__ import annotations

import time


def _make_candles(values: list[float]) -> list[dict]:
    return [{"close": v, "open": v, "high": v, "low": v, "volume": 1000} for v in values]


# ---------------------------------------------------------------------------
# India impact strings
# ---------------------------------------------------------------------------

class TestIndiaImpact:
    def test_crude_rising(self):
        from src.intelligence.global_pulse import _india_impact
        result = _india_impact("crude_oil", 3.0)
        assert "inflationary" in result.lower() or "energy" in result.lower()

    def test_crude_falling(self):
        from src.intelligence.global_pulse import _india_impact
        result = _india_impact("crude_oil", -3.0)
        assert "falling crude" in result.lower() or "deflationary" in result.lower()

    def test_crude_stable(self):
        from src.intelligence.global_pulse import _india_impact
        result = _india_impact("crude_oil", 0.5)
        assert "stable" in result.lower()

    def test_dxy_strengthening(self):
        from src.intelligence.global_pulse import _india_impact
        result = _india_impact("dxy", 1.0)
        assert "outflow" in result.lower() or "strengthening" in result.lower()

    def test_dxy_weakening(self):
        from src.intelligence.global_pulse import _india_impact
        result = _india_impact("dxy", -1.0)
        assert "inflow" in result.lower() or "weakening" in result.lower()

    def test_sp500_up(self):
        from src.intelligence.global_pulse import _india_impact
        result = _india_impact("sp500", 2.0)
        assert "positive" in result.lower() or "strength" in result.lower()

    def test_sp500_down(self):
        from src.intelligence.global_pulse import _india_impact
        result = _india_impact("sp500", -2.0)
        assert "risk-off" in result.lower() or "gap-down" in result.lower()

    def test_unknown_key(self):
        from src.intelligence.global_pulse import _india_impact
        result = _india_impact("unknown_asset", 5.0)
        assert result  # non-empty


# ---------------------------------------------------------------------------
# Overall sentiment
# ---------------------------------------------------------------------------

class TestOverallSentiment:
    def _build_assets(self, sp500_pct=0.0, gold_pct=0.0, dxy_pct=0.0, crude_pct=0.0):
        return {
            "sp500":     {"change_pct": sp500_pct},
            "gold":      {"change_pct": gold_pct},
            "dxy":       {"change_pct": dxy_pct},
            "crude_oil": {"change_pct": crude_pct},
            "us_10y_yield": {"change_pct": 0.0},
        }

    def test_sp500_down_triggers_risk_off(self):
        from src.intelligence.global_pulse import _overall_sentiment
        assets = self._build_assets(sp500_pct=-2.0)
        assert _overall_sentiment(assets) == "RISK_OFF"

    def test_sp500_up_contributes_risk_on(self):
        from src.intelligence.global_pulse import _overall_sentiment
        # sp500 +2% = +2 risk_on votes → RISK_ON
        assets = self._build_assets(sp500_pct=2.0)
        assert _overall_sentiment(assets) == "RISK_ON"

    def test_neutral_when_mixed(self):
        from src.intelligence.global_pulse import _overall_sentiment
        assets = self._build_assets(sp500_pct=0.0)
        assert _overall_sentiment(assets) == "NEUTRAL"

    def test_gold_risk_off(self):
        from src.intelligence.global_pulse import _overall_sentiment
        # gold +2% (+1 risk_off) + dxy +1% (+1 risk_off) = 2 → RISK_OFF
        assets = self._build_assets(gold_pct=2.0, dxy_pct=1.0)
        assert _overall_sentiment(assets) == "RISK_OFF"

    def test_missing_change_pct_ignored(self):
        from src.intelligence.global_pulse import _overall_sentiment
        assets = {k: {"change_pct": None} for k in
                  ("sp500", "gold", "dxy", "crude_oil", "us_10y_yield")}
        assert _overall_sentiment(assets) == "NEUTRAL"


# ---------------------------------------------------------------------------
# get_global_pulse — happy path
# ---------------------------------------------------------------------------

class TestGetGlobalPulse:
    def test_returns_expected_keys(self, monkeypatch):
        import src.intelligence.global_pulse as gp_mod

        with gp_mod._LOCK:
            gp_mod._CACHE.clear()

        class FakeSvc:
            def get_historical(self, ticker, start, end, interval):
                return _make_candles([100.0, 101.0])

        monkeypatch.setattr(gp_mod, "get_market", lambda: FakeSvc())
        result = gp_mod.get_global_pulse()

        assert "error" not in result
        assert "assets" in result
        assert "overall_sentiment" in result
        assert result["overall_sentiment"] in ("RISK_ON", "RISK_OFF", "NEUTRAL")

    def test_all_five_assets_present(self, monkeypatch):
        import src.intelligence.global_pulse as gp_mod

        with gp_mod._LOCK:
            gp_mod._CACHE.clear()

        class FakeSvc:
            def get_historical(self, ticker, start, end, interval):
                return _make_candles([100.0, 102.0])

        monkeypatch.setattr(gp_mod, "get_market", lambda: FakeSvc())
        result = gp_mod.get_global_pulse()

        for key in ("crude_oil", "gold", "dxy", "sp500", "us_10y_yield"):
            assert key in result["assets"], f"missing asset: {key}"

    def test_asset_with_no_data_shows_none(self, monkeypatch):
        import src.intelligence.global_pulse as gp_mod

        with gp_mod._LOCK:
            gp_mod._CACHE.clear()

        class FakeSvc:
            def get_historical(self, ticker, start, end, interval):
                return []

        monkeypatch.setattr(gp_mod, "get_market", lambda: FakeSvc())
        result = gp_mod.get_global_pulse()

        assert "error" not in result
        for asset in result["assets"].values():
            assert asset["change_pct"] is None

    def test_exception_returns_error(self, monkeypatch):
        import src.intelligence.global_pulse as gp_mod

        with gp_mod._LOCK:
            gp_mod._CACHE.clear()

        def boom():
            raise RuntimeError("network down")

        monkeypatch.setattr(gp_mod, "get_market", boom)
        result = gp_mod.get_global_pulse()
        assert "error" in result


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------

class TestGlobalPulseCaching:
    def test_second_call_uses_cache(self, monkeypatch):
        import src.intelligence.global_pulse as gp_mod

        with gp_mod._LOCK:
            gp_mod._CACHE.clear()

        call_count = 0

        class FakeSvc:
            def get_historical(self, ticker, *a, **kw):
                nonlocal call_count
                call_count += 1
                return _make_candles([100.0, 101.0])

        monkeypatch.setattr(gp_mod, "get_market", lambda: FakeSvc())
        gp_mod.get_global_pulse()
        gp_mod.get_global_pulse()
        # 5 assets × 1 call each = 5 on first fetch; 0 on second
        assert call_count == 5

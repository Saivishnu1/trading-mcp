"""
Unit and integration tests for src/dashboard/service.py.

_build_summary is pure — no mocking required.
build_dashboard mocks _analyze_technicals, _load_closes, and get_options_service.
"""
import pytest

from src.dashboard.service import _build_summary, build_dashboard

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_tech_section(rsi=60.0, ema20=100.0, ema50=98.0,
                       adx=18.0, atr=2.0):
    return {
        "rsi": rsi, "ema20": ema20, "ema50": ema50,
        "macd": {"macd": 0.5, "signal": 0.3, "histogram": 0.2},
        "adx": adx, "plus_di": 25.0, "minus_di": 10.0, "atr": atr,
    }


def _make_opts_section(pcr=1.1):
    return {
        "expiry": "26-Jun-2025",
        "pcr": pcr,
        "pcr_interpretation": "mildly bullish",
        "max_pain": 24000.0,
        "distance_from_spot": 0.0,
        "supports": [23000.0],
        "resistances": [25000.0],
        "nearest_support": 23000.0,
        "nearest_resistance": 25000.0,
    }


def _make_analysis_section(regime="BULL_TREND", confidence=75):
    return {"regime": regime, "confidence": confidence, "signal": "BUY"}


def _tech(rsi=65.0, ema20=100.0, ema50=90.0, adx=30.0, price=101.0,
          atr=2.0, macd_val=0.5, macd_sig=0.3):
    return {
        "symbol": "NIFTY", "last_close": price, "candles_used": 150,
        "rsi_14": rsi, "ema_20": ema20, "ema_50": ema50,
        "macd": {"macd": macd_val, "signal": macd_sig,
                 "histogram": round(macd_val - macd_sig, 4)},
        "adx_14": {"adx": adx, "plus_di": 28.0, "minus_di": 12.0},
        "atr_14": atr,
    }


BULL_TECH = _tech()


# ---------------------------------------------------------------------------
# _build_summary — pure function
# ---------------------------------------------------------------------------

class TestBuildSummary:

    def test_above_both_emas_clause(self):
        tech = _make_tech_section(ema20=100.0, ema50=98.0)
        s = _build_summary("NIFTY", spot=101.0, tech=tech,
                            opts=_make_opts_section(), analysis=_make_analysis_section(),
                            signal="BUY")
        assert "above both" in s.lower()

    def test_below_both_emas_clause(self):
        tech = _make_tech_section(ema20=102.0, ema50=100.0)
        s = _build_summary("NIFTY", spot=99.0, tech=tech,
                            opts=_make_opts_section(), analysis=_make_analysis_section(),
                            signal="SELL")
        assert "below both" in s.lower()

    def test_bullish_pcr_clause(self):
        tech = _make_tech_section()
        s = _build_summary("NIFTY", spot=101.0, tech=tech,
                            opts=_make_opts_section(pcr=1.4),
                            analysis=_make_analysis_section(), signal="BUY")
        assert "bullish" in s.lower()

    def test_bearish_pcr_clause(self):
        tech = _make_tech_section()
        s = _build_summary("NIFTY", spot=101.0, tech=tech,
                            opts=_make_opts_section(pcr=0.5),
                            analysis=_make_analysis_section(), signal="SELL")
        assert "bearish" in s.lower()

    def test_no_pcr_unavailable_clause(self):
        opts = _make_opts_section()
        opts["pcr"] = None
        tech = _make_tech_section()
        s = _build_summary("NIFTY", 101.0, tech, opts, _make_analysis_section(), "BUY")
        assert "unavailable" in s.lower()

    def test_strong_rsi_momentum_clause(self):
        tech = _make_tech_section(rsi=70.0)
        s = _build_summary("NIFTY", 101.0, tech, _make_opts_section(),
                            _make_analysis_section(), "BUY")
        assert "strong" in s.lower() or "overbought" in s.lower()

    def test_neutral_rsi_momentum_clause(self):
        tech = _make_tech_section(rsi=50.0)
        s = _build_summary("NIFTY", 101.0, tech, _make_opts_section(),
                            _make_analysis_section(), "BUY")
        assert "neutral" in s.lower()

    def test_high_adx_trend_strength(self):
        tech = _make_tech_section(adx=35.0)
        s = _build_summary("NIFTY", 101.0, tech, _make_opts_section(),
                            _make_analysis_section(), "BUY")
        assert "strong" in s.lower()

    def test_low_adx_trend_strength(self):
        tech = _make_tech_section(adx=12.0)
        s = _build_summary("NIFTY", 101.0, tech, _make_opts_section(),
                            _make_analysis_section(), "BUY")
        assert "low" in s.lower()

    def test_buy_bias_clause(self):
        tech = _make_tech_section()
        s = _build_summary("NIFTY", 101.0, tech, _make_opts_section(),
                            _make_analysis_section(), "BUY")
        assert "bullish" in s.lower()

    def test_sell_bias_clause(self):
        tech = _make_tech_section()
        s = _build_summary("NIFTY", 101.0, tech, _make_opts_section(),
                            _make_analysis_section(regime="BEAR_TREND"), "SELL")
        assert "bearish" in s.lower()

    def test_symbol_in_summary(self):
        tech = _make_tech_section()
        s = _build_summary("NIFTY", 101.0, tech, _make_opts_section(),
                            _make_analysis_section(), "BUY")
        assert "NIFTY" in s

    def test_returns_non_empty_string(self):
        tech = _make_tech_section()
        s = _build_summary("NIFTY", 101.0, tech, _make_opts_section(),
                            _make_analysis_section(), "BUY")
        assert isinstance(s, str)
        assert len(s) > 20


# ---------------------------------------------------------------------------
# build_dashboard — integration
# ---------------------------------------------------------------------------

def _make_ohlcv(n=200, start=1000.0, step=3.0):
    closes = [start + step * i for i in range(n)]
    highs  = [c + 5.0 for c in closes]
    lows   = [c - 5.0 for c in closes]
    return closes, highs, lows


class TestBuildDashboard:

    def _patch_all(self, monkeypatch, chain_data, tech=None):
        t = tech or BULL_TECH
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda s, lookback_days=150: t)
        closes, highs, lows = _make_ohlcv()
        monkeypatch.setattr("src.dashboard.service._load_closes",
                            lambda symbol, lookback_days=150: (closes, highs, lows))
        from unittest.mock import MagicMock
        svc = MagicMock()
        svc.get_option_chain.return_value = chain_data
        monkeypatch.setattr("src.dashboard.service.get_options_service", lambda: svc)
        monkeypatch.setattr("src.planner.trade_plan.get_options_service",
                            lambda: _raise_svc())

    def test_returns_required_top_level_keys(self, monkeypatch, chain_data):
        self._patch_all(monkeypatch, chain_data)
        r = build_dashboard("NIFTY")
        for key in ("symbol", "spot_price", "options", "technicals",
                    "analysis", "trade_setup", "strategy", "summary"):
            assert key in r

    def test_symbol_uppercased(self, monkeypatch, chain_data):
        self._patch_all(monkeypatch, chain_data)
        r = build_dashboard("nifty")
        assert r["symbol"] == "NIFTY"

    def test_spot_price_from_chain(self, monkeypatch, chain_data):
        self._patch_all(monkeypatch, chain_data)
        r = build_dashboard("NIFTY")
        # Chain spot=24000; technicals spot is from last_close of OHLCV
        # build_dashboard uses chain spot first (spot_chain)
        assert r["spot_price"] == 24000.0

    def test_options_section_has_pcr(self, monkeypatch, chain_data):
        self._patch_all(monkeypatch, chain_data)
        r = build_dashboard("NIFTY")
        assert "pcr" in r["options"]

    def test_technicals_section_has_rsi(self, monkeypatch, chain_data):
        self._patch_all(monkeypatch, chain_data)
        r = build_dashboard("NIFTY")
        assert "rsi" in r["technicals"]
        assert r["technicals"]["rsi"] is not None

    def test_analysis_section_has_regime(self, monkeypatch, chain_data):
        self._patch_all(monkeypatch, chain_data)
        r = build_dashboard("NIFTY")
        assert "regime" in r["analysis"]
        assert r["analysis"]["regime"] is not None

    def test_trade_setup_has_both_schemas(self, monkeypatch, chain_data):
        self._patch_all(monkeypatch, chain_data)
        r = build_dashboard("NIFTY")
        ts = r["trade_setup"]
        if "error" not in ts:
            for field in ("entry", "stoploss", "target",
                          "entry_above", "entry_below"):
                assert field in ts

    def test_summary_is_non_empty_string(self, monkeypatch, chain_data):
        self._patch_all(monkeypatch, chain_data)
        r = build_dashboard("NIFTY")
        assert isinstance(r["summary"], str)
        assert len(r["summary"]) > 20

    def test_options_failure_isolated(self, monkeypatch, chain_data):
        """A failed options section must NOT prevent technicals/analysis."""
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda s, lookback_days=150: BULL_TECH)
        closes, highs, lows = _make_ohlcv()
        monkeypatch.setattr("src.dashboard.service._load_closes",
                            lambda symbol, lookback_days=150: (closes, highs, lows))
        monkeypatch.setattr("src.dashboard.service.get_options_service",
                            lambda: _raise_svc())
        monkeypatch.setattr("src.planner.trade_plan.get_options_service",
                            lambda: _raise_svc())
        r = build_dashboard("NIFTY")
        # Options failed → error key in options section
        assert "error" in r["options"]
        # But technicals and analysis should still be present and not errored
        assert "rsi" in r["technicals"]
        assert "regime" in r["analysis"]

    def test_technicals_failure_isolated(self, monkeypatch, chain_data):
        """A failed technicals section must NOT prevent options/analysis."""
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda s, lookback_days=150: BULL_TECH)
        # Return empty OHLCV → technicals section returns error dict
        monkeypatch.setattr("src.dashboard.service._load_closes",
                            lambda symbol, lookback_days=150: (None, None, None))
        from unittest.mock import MagicMock
        svc = MagicMock()
        svc.get_option_chain.return_value = chain_data
        monkeypatch.setattr("src.dashboard.service.get_options_service", lambda: svc)
        monkeypatch.setattr("src.planner.trade_plan.get_options_service",
                            lambda: _raise_svc())
        r = build_dashboard("NIFTY")
        assert "error" in r["technicals"]
        assert "regime" in r["analysis"]


class _raise_svc:
    def get_option_chain(self, *a, **kw):
        raise RuntimeError("NSE unavailable in tests")

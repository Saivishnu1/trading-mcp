"""
Unit tests for src/analysis/regime.py.

calculate_risk_reward and calculate_position_size are pure math — no mocking.
detect_market_regime mocks _analyze_technicals.
"""
import pytest

from src.analysis.regime import (
    _is_invalid,
    calculate_position_size,
    calculate_risk_reward,
    detect_market_regime,
)

# ---------------------------------------------------------------------------
# Local tech snapshots (regime-specific indicator dicts)
# ---------------------------------------------------------------------------

def _tech(symbol, rsi, ema20, ema50, adx, price, atr=2.0,
          macd_val=0.5, macd_sig=0.3):
    return {
        "symbol": symbol.upper(),
        "last_close": price,
        "candles_used": 150,
        "rsi_14": rsi,
        "ema_20": ema20,
        "ema_50": ema50,
        "macd": {"macd": macd_val, "signal": macd_sig,
                 "histogram": round(macd_val - macd_sig, 4)},
        "adx_14": {"adx": adx, "plus_di": 28.0, "minus_di": 12.0},
        "atr_14": atr,
    }


BULL  = _tech("NIFTY", rsi=65.0, ema20=100.0, ema50=90.0,  adx=30.0, price=101.0)
BEAR  = _tech("NIFTY", rsi=35.0, ema20=90.0,  ema50=100.0, adx=28.0, price=89.0,
              macd_val=-0.5, macd_sig=-0.3)
RANGE = _tech("NIFTY", rsi=50.0, ema20=100.0, ema50=98.0,  adx=15.0, price=100.5,
              macd_val=0.1, macd_sig=0.0)
BKOUT = _tech("NIFTY", rsi=60.0, ema20=100.0, ema50=98.0,  adx=22.0, price=101.0)
# Fallback NEUTRAL_BULLISH: adx in [20,25], rsi not >55, price >= ema20
NB    = _tech("NIFTY", rsi=50.0, ema20=100.0, ema50=99.0,  adx=22.0, price=101.0,
              macd_val=0.1, macd_sig=0.0)
# Fallback NEUTRAL_BEARISH: adx in [20,25], rsi not <45, price < ema20
NR    = _tech("NIFTY", rsi=50.0, ema20=102.0, ema50=100.0, adx=22.0, price=99.0,
              macd_val=-0.1, macd_sig=0.0)
# Perfectly balanced → NEUTRAL signal
NEUT  = _tech("NIFTY", rsi=50.0, ema20=100.0, ema50=100.0, adx=15.0, price=100.0,
              macd_val=0.1, macd_sig=0.1)


# ---------------------------------------------------------------------------
# calculate_risk_reward — pure math
# ---------------------------------------------------------------------------

class TestCalculateRiskReward:

    def test_basic(self):
        r = calculate_risk_reward(entry=100, stoploss=95, target=110)
        assert r["risk"] == pytest.approx(5.0, rel=1e-4)
        assert r["reward"] == pytest.approx(10.0, rel=1e-4)
        assert r["rr"] == pytest.approx(2.0, rel=1e-4)

    def test_rr_less_than_one(self):
        r = calculate_risk_reward(entry=100, stoploss=90, target=105)
        assert r["rr"] == pytest.approx(0.5, rel=1e-4)

    def test_returns_all_fields(self):
        r = calculate_risk_reward(100, 95, 110)
        for key in ("entry", "stoploss", "target", "risk", "reward", "rr"):
            assert key in r

    def test_entry_equals_stoploss_rr_none(self):
        r = calculate_risk_reward(entry=100, stoploss=100, target=110)
        assert r["rr"] is None

    def test_invalid_entry_returns_error(self):
        r = calculate_risk_reward(entry=0, stoploss=95, target=110)
        assert "error" in r

    def test_invalid_target_returns_error(self):
        r = calculate_risk_reward(entry=100, stoploss=95, target=0)
        assert "error" in r

    def test_non_numeric_returns_error(self):
        r = calculate_risk_reward(entry="abc", stoploss=95, target=110)
        assert "error" in r

    def test_sell_side_works(self):
        # SELL: entry below stoploss, target below entry
        r = calculate_risk_reward(entry=95, stoploss=100, target=85)
        assert r["risk"] == pytest.approx(5.0, rel=1e-4)
        assert r["reward"] == pytest.approx(10.0, rel=1e-4)
        assert r["rr"] == pytest.approx(2.0, rel=1e-4)


# ---------------------------------------------------------------------------
# calculate_position_size — pure math
# ---------------------------------------------------------------------------

class TestCalculatePositionSize:

    def test_basic(self):
        r = calculate_position_size(capital=100_000, risk_percent=1.0,
                                    entry=100, stoploss=95)
        # risk_amount = 100_000 * 0.01 = 1000
        # stop_distance = 5
        # position_size = 1000/5 = 200
        assert r["position_size"] == pytest.approx(200.0, rel=1e-4)
        assert r["risk_amount"] == pytest.approx(1000.0, rel=1e-4)

    def test_returns_all_fields(self):
        r = calculate_position_size(100_000, 2.0, 200, 190)
        for key in ("capital", "risk_percent", "risk_amount", "position_size"):
            assert key in r

    def test_entry_equals_stoploss_size_none(self):
        r = calculate_position_size(100_000, 1.0, 100, 100)
        assert r["position_size"] is None

    def test_invalid_capital_returns_error(self):
        r = calculate_position_size(capital=0, risk_percent=1.0, entry=100, stoploss=95)
        assert "error" in r

    def test_invalid_risk_percent_returns_error(self):
        r = calculate_position_size(100_000, risk_percent=0, entry=100, stoploss=95)
        assert "error" in r

    def test_larger_stop_means_smaller_size(self):
        r_tight = calculate_position_size(100_000, 1.0, 100, 98)   # 2-pt stop
        r_wide  = calculate_position_size(100_000, 1.0, 100, 90)   # 10-pt stop
        assert r_tight["position_size"] > r_wide["position_size"]


# ---------------------------------------------------------------------------
# _is_invalid — unit tests for the NaN/None guard helper (Fix 2a)
# ---------------------------------------------------------------------------

class TestIsInvalid:

    def test_none_is_invalid(self):
        assert _is_invalid(None) is True

    def test_nan_float_is_invalid(self):
        assert _is_invalid(float("nan")) is True

    def test_regular_float_is_valid(self):
        assert _is_invalid(65.5) is False

    def test_zero_is_valid(self):
        # zero is a legitimate indicator value (e.g. ADX can be 0)
        assert _is_invalid(0.0) is False


# ---------------------------------------------------------------------------
# detect_market_regime — mocks _analyze_technicals
# ---------------------------------------------------------------------------

class TestDetectMarketRegime:

    def test_bull_trend(self, monkeypatch):
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda s, lookback_days=150: BULL)
        r = detect_market_regime("NIFTY")
        assert r["regime"] == "BULL_TREND"
        assert r["confidence"] >= 70

    def test_bear_trend(self, monkeypatch):
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda s, lookback_days=150: BEAR)
        r = detect_market_regime("NIFTY")
        assert r["regime"] == "BEAR_TREND"

    def test_range_bound(self, monkeypatch):
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda s, lookback_days=150: RANGE)
        r = detect_market_regime("NIFTY")
        assert r["regime"] == "RANGE_BOUND"

    def test_breakout_potential(self, monkeypatch):
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda s, lookback_days=150: BKOUT)
        r = detect_market_regime("NIFTY")
        assert r["regime"] == "BREAKOUT_POTENTIAL"

    def test_neutral_bullish_fallback(self, monkeypatch):
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda s, lookback_days=150: NB)
        r = detect_market_regime("NIFTY")
        assert r["regime"] == "NEUTRAL_BULLISH"

    def test_neutral_bearish_fallback(self, monkeypatch):
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda s, lookback_days=150: NR)
        r = detect_market_regime("NIFTY")
        assert r["regime"] == "NEUTRAL_BEARISH"

    def test_returns_required_fields(self, monkeypatch):
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda s, lookback_days=150: BULL)
        r = detect_market_regime("NIFTY")
        for key in ("symbol", "regime", "confidence", "price",
                    "rsi", "ema20", "ema50", "adx", "atr"):
            assert key in r

    def test_bad_symbol_returns_error(self, monkeypatch):
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda s, lookback_days=150: {"error": "no data"})
        r = detect_market_regime("BADINPUT")
        assert "error" in r

    def test_symbol_uppercased_in_output(self, monkeypatch):
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda s, lookback_days=150: BULL)
        r = detect_market_regime("nifty")
        assert r["symbol"] == "NIFTY"

    def test_regime_returns_error_for_nan_rsi(self, monkeypatch):
        nan_tech = {**BULL, "rsi_14": float("nan")}
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda s, lookback_days=150: nan_tech)
        r = detect_market_regime("NIFTY")
        assert "error" in r, (
            "NaN rsi_14 must cause detect_market_regime to return an error dict"
        )


# ---------------------------------------------------------------------------
# TestConfidenceScale — B1 (Phase 14.6): one 0–85 scale, rescaled not clamped
# ---------------------------------------------------------------------------

class TestConfidenceScale:
    def test_scale_helper_maps_band(self):
        from src.analysis.regime import _scale_confidence, MAX_CONFIDENCE
        assert _scale_confidence(100) == MAX_CONFIDENCE == 85
        assert _scale_confidence(0) == 0
        # No flat top below the ceiling: distinct internal scores stay distinct.
        assert _scale_confidence(80) < _scale_confidence(100)
        assert _scale_confidence(60) < _scale_confidence(80)

    def test_regime_confidence_within_band(self, monkeypatch):
        import src.analysis.regime as regime
        monkeypatch.setattr(regime, "_analyze_technicals",
                            lambda s, lookback_days=150: BULL)
        r = detect_market_regime("NIFTY")
        assert 0 <= r["confidence"] <= 85


# ---------------------------------------------------------------------------
# TestAnalysisCache — C1 (Phase 14.6): one fetch per (symbol, lookback) flow
# ---------------------------------------------------------------------------

class TestAnalysisCache:
    def _candles(self, n=160):
        return [
            {"date": f"2026-01-{(i % 28) + 1:02d}T00:00:00",
             "open": 100.0 + i, "high": 102.0 + i, "low": 99.0 + i,
             "close": 100.5 + i, "volume": 1000}
            for i in range(n)
        ]

    def test_clear_cache_forces_refetch(self, monkeypatch):
        import src.analysis.regime as regime
        calls = {"n": 0}

        def _counting_loader(symbol, lookback, interval="1d"):
            calls["n"] += 1
            return self._candles()

        monkeypatch.setattr(regime, "_load_candles", _counting_loader)
        regime.clear_analysis_cache()

        regime.detect_market_regime("NIFTY")
        regime.clear_analysis_cache()
        regime.detect_market_regime("NIFTY")
        assert calls["n"] == 2, "clearing the cache must force a fresh fetch"

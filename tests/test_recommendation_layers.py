"""Priority 9 — Recommendation Architecture: Options + Risk layer regression tests.

RL-1  attach_options_layer surfaces real fields when the options engine succeeds
RL-2  attach_options_layer returns available=False (not raise) on an engine error
RL-3  attach_options_layer returns available=False (not raise) on an unexpected exception
RL-4  attach_risk_layer surfaces real fields when the risk engine succeeds
RL-5  attach_risk_layer returns available=False (not raise) on an engine error
RL-6  generate_trade_setup_tf defaults (both False) never call either engine
RL-7  include_options_layer=True attaches options_layer without affecting confidence/signal
RL-8  include_risk_layer=True attaches risk_layer without affecting confidence/signal
RL-9  both layers can be requested together independently
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

from src.analysis.regime import generate_trade_setup_tf
from src.timeframe.layers import attach_options_layer, attach_risk_layer


def _fresh_daily_date() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _fake_tech_bull():
    return {
        "symbol": "NIFTY", "last_close": 100.0, "candles_used": 150,
        "data_source": "yfinance_eod_adjusted", "last_candle_date": _fresh_daily_date(),
        "rsi_14": 65.0, "ema_20": 95.0, "ema_50": 90.0,
        "macd": {"macd": 0.5, "signal": 0.3, "histogram": 0.2},
        "adx_14": {"adx": 30.0, "plus_di": 28.0, "minus_di": 12.0},
        "atr_14": 2.0,
    }


class TestRL1OptionsLayerSuccess:
    def test_surfaces_real_fields(self):
        fake_result = {
            "symbol": "NIFTY", "expiry": "2026-07-31", "spot": 24000.0,
            "pcr": 1.05, "pcr_interpretation": "neutral",
            "max_pain": 24000.0, "distance_from_max_pain": 0.0,
            "iv": {"atm_iv": 12.5, "iv_skew": 0.2},
        }
        with patch("src.options_awareness.engine.OptionsAwarenessEngine.analyze", return_value=fake_result):
            result = attach_options_layer("NIFTY")
        assert result["available"] is True
        assert result["pcr"] == 1.05
        assert result["max_pain"] == 24000.0
        assert result["atm_iv"] == 12.5


class TestRL2OptionsLayerEngineError:
    def test_error_key_surfaces_as_unavailable(self):
        with patch("src.options_awareness.engine.OptionsAwarenessEngine.analyze",
                   return_value={"symbol": "RELIANCE", "error": "no option chain for this symbol"}):
            result = attach_options_layer("RELIANCE")
        assert result["available"] is False
        assert "reason" in result


class TestRL3OptionsLayerException:
    def test_exception_does_not_raise(self):
        with patch("src.options_awareness.engine.OptionsAwarenessEngine.analyze",
                   side_effect=RuntimeError("boom")):
            result = attach_options_layer("NIFTY")
        assert result["available"] is False
        assert "boom" in result["reason"]


class TestRL4RiskLayerSuccess:
    def test_surfaces_real_fields(self):
        fake_result = {
            "symbol": "NIFTY", "score": 42, "rating": "MODERATE",
            "confidence": 0.85, "is_degraded": False,
            "recommendation": "Normal caution advised.",
        }
        with patch("src.intelligence.risk.get_market_risk_score", return_value=fake_result):
            result = attach_risk_layer("NIFTY")
        assert result["available"] is True
        assert result["score"] == 42
        assert result["rating"] == "MODERATE"


class TestRL5RiskLayerEngineError:
    def test_error_key_surfaces_as_unavailable(self):
        with patch("src.intelligence.risk.get_market_risk_score",
                   return_value={"error": "risk data unavailable"}):
            result = attach_risk_layer("NIFTY")
        assert result["available"] is False


class TestRL6DefaultsNeverCallEitherEngine:
    def test_neither_layer_called_by_default(self, monkeypatch):
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda symbol, lookback_days=150, interval="daily": _fake_tech_bull())
        with patch("src.timeframe.layers.attach_options_layer") as opt_mock, \
             patch("src.timeframe.layers.attach_risk_layer") as risk_mock:
            result = generate_trade_setup_tf("NIFTY", "SWING", "day")
        assert "options_layer" not in result
        assert "risk_layer" not in result
        opt_mock.assert_not_called()
        risk_mock.assert_not_called()


class TestRL7OptionsLayerOptIn:
    def test_options_layer_attached_without_affecting_signal(self, monkeypatch):
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda symbol, lookback_days=150, interval="daily": _fake_tech_bull())
        baseline = generate_trade_setup_tf("NIFTY", "SWING", "day")
        with patch("src.options_awareness.engine.OptionsAwarenessEngine.analyze",
                   return_value={"symbol": "NIFTY", "expiry": "x", "spot": 100.0,
                                 "pcr": 0.9, "pcr_interpretation": "neutral",
                                 "max_pain": 100.0, "distance_from_max_pain": 0.0,
                                 "iv": {"atm_iv": 15.0, "iv_skew": 0.1}}):
            with_options = generate_trade_setup_tf("NIFTY", "SWING", "day", include_options_layer=True)
        assert "options_layer" in with_options
        assert with_options["options_layer"]["available"] is True
        assert with_options["signal"] == baseline["signal"]
        assert with_options["confidence"] == baseline["confidence"]


class TestRL8RiskLayerOptIn:
    def test_risk_layer_attached_without_affecting_signal(self, monkeypatch):
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda symbol, lookback_days=150, interval="daily": _fake_tech_bull())
        baseline = generate_trade_setup_tf("NIFTY", "SWING", "day")
        with patch("src.intelligence.risk.get_market_risk_score",
                   return_value={"symbol": "NIFTY", "score": 30, "rating": "LOW",
                                 "confidence": 1.0, "is_degraded": False, "recommendation": "ok"}):
            with_risk = generate_trade_setup_tf("NIFTY", "SWING", "day", include_risk_layer=True)
        assert "risk_layer" in with_risk
        assert with_risk["risk_layer"]["available"] is True
        assert with_risk["signal"] == baseline["signal"]
        assert with_risk["confidence"] == baseline["confidence"]


class TestRL9BothLayersTogether:
    def test_both_layers_can_be_requested_together(self, monkeypatch):
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda symbol, lookback_days=150, interval="daily": _fake_tech_bull())
        with patch("src.options_awareness.engine.OptionsAwarenessEngine.analyze",
                   return_value={"symbol": "NIFTY", "expiry": "x", "spot": 100.0,
                                 "pcr": 0.9, "pcr_interpretation": "neutral",
                                 "max_pain": 100.0, "distance_from_max_pain": 0.0,
                                 "iv": {"atm_iv": 15.0, "iv_skew": 0.1}}), \
             patch("src.intelligence.risk.get_market_risk_score",
                   return_value={"symbol": "NIFTY", "score": 30, "rating": "LOW",
                                 "confidence": 1.0, "is_degraded": False, "recommendation": "ok"}):
            result = generate_trade_setup_tf(
                "NIFTY", "SWING", "day", include_options_layer=True, include_risk_layer=True,
            )
        assert result["options_layer"]["available"] is True
        assert result["risk_layer"]["available"] is True

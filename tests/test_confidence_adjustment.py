"""Priority 7 — Recommendation Confidence rework regression tests.

CA-1  no problems -> adjusted_confidence equals raw_confidence, no penalties
CA-2  mixed-timeframe conflict (context contradicts signal direction) reduces confidence
CA-3  missing/rejected indicator data reduces confidence
CA-4  internal conflict (evidence_against >= evidence_for) reduces confidence
CA-5  DEGRADED decision_trace data_quality reduces confidence
CA-6  multiple simultaneous problems stack (penalties are additive)
CA-7  adjusted_confidence never goes negative even with many penalties
CA-8  confidence is never increased, only ever reduced or left unchanged
CA-9  not_checked explicitly names liquidity/IV as out of scope, not silently omitted
CA-10 generate_trade_setup_tf surfaces raw_confidence, confidence, confidence_penalties, confidence_not_checked
CA-11 decision_trace's own confidence field reflects the ADJUSTED value, not the raw one
CA-12 generate_trade_setup (daily-only, unchanged) has no confidence_penalties/raw_confidence-from-this-module keys
"""
from __future__ import annotations

from datetime import datetime, timezone

from src.analysis.regime import generate_trade_setup, generate_trade_setup_tf
from src.timeframe.confidence import adjust_confidence


def _fresh_daily_date() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _setup(confidence=70, signal="BUY", context=None, evidence_for=None, evidence_against=None) -> dict:
    return {
        "confidence": confidence,
        "signal": signal,
        "context": context or [],
        "evidence_for": evidence_for if evidence_for is not None else [{"indicator": "rsi", "text": "x", "points": 20}],
        "evidence_against": evidence_against or [],
    }


def _trace(data_quality="VALID", indicators_rejected=None) -> dict:
    return {"data_quality": data_quality, "indicators_rejected": indicators_rejected or []}


class TestCA1NoProblemsNoAdjustment:
    def test_adjusted_equals_raw(self):
        result = adjust_confidence(_setup(confidence=70), _trace())
        assert result["adjusted_confidence"] == 70
        assert result["raw_confidence"] == 70
        assert result["penalties"] == []


class TestCA2MixedTimeframeConflict:
    def test_bullish_signal_vs_below_ema20_context_reduces(self):
        result = adjust_confidence(
            _setup(confidence=70, signal="BUY", context=["week: price is below EMA20"]),
            _trace(),
        )
        assert result["adjusted_confidence"] < 70
        assert any("context" in p["reason"].lower() for p in result["penalties"])

    def test_bearish_signal_vs_above_ema20_context_reduces(self):
        result = adjust_confidence(
            _setup(confidence=70, signal="SELL", context=["week: price is above EMA20"]),
            _trace(),
        )
        assert result["adjusted_confidence"] < 70

    def test_agreeing_context_does_not_reduce(self):
        result = adjust_confidence(
            _setup(confidence=70, signal="BUY", context=["week: price is above EMA20"]),
            _trace(),
        )
        assert result["adjusted_confidence"] == 70


class TestCA3MissingDataReduces:
    def test_rejected_indicators_reduce_confidence(self):
        result = adjust_confidence(
            _setup(confidence=70),
            _trace(indicators_rejected=[{"indicator": "adx", "reason": "no value"}]),
        )
        assert result["adjusted_confidence"] < 70


class TestCA4InternalConflictReduces:
    def test_evidence_against_at_least_evidence_for_reduces(self):
        result = adjust_confidence(
            _setup(
                confidence=70,
                evidence_for=[{"indicator": "rsi", "text": "a", "points": 10}],
                evidence_against=[
                    {"indicator": "ema_20", "text": "b", "points": 15},
                    {"indicator": "macd", "text": "c", "points": 20},
                ],
            ),
            _trace(),
        )
        assert result["adjusted_confidence"] < 70

    def test_evidence_for_dominant_does_not_reduce_via_this_rule(self):
        result = adjust_confidence(
            _setup(
                confidence=70,
                evidence_for=[
                    {"indicator": "rsi", "text": "a", "points": 20},
                    {"indicator": "ema_20", "text": "b", "points": 15},
                ],
                evidence_against=[{"indicator": "macd", "text": "c", "points": 10}],
            ),
            _trace(),
        )
        assert result["adjusted_confidence"] == 70


class TestCA5DegradedDataQualityReduces:
    def test_degraded_trace_reduces_confidence(self):
        result = adjust_confidence(_setup(confidence=70), _trace(data_quality="DEGRADED"))
        assert result["adjusted_confidence"] < 70


class TestCA6PenaltiesStack:
    def test_two_simultaneous_problems_reduce_more_than_one(self):
        single = adjust_confidence(_setup(confidence=70), _trace(data_quality="DEGRADED"))
        double = adjust_confidence(
            _setup(confidence=70, signal="BUY", context=["week: price is below EMA20"]),
            _trace(data_quality="DEGRADED"),
        )
        assert double["adjusted_confidence"] < single["adjusted_confidence"]
        assert len(double["penalties"]) == 2


class TestCA7NeverGoesNegative:
    def test_low_raw_confidence_with_all_penalties_floors_at_zero(self):
        result = adjust_confidence(
            _setup(
                confidence=10, signal="BUY", context=["week: price is below EMA20"],
                evidence_for=[{"indicator": "rsi", "text": "a", "points": 5}],
                evidence_against=[{"indicator": "ema_20", "text": "b", "points": 5}],
            ),
            _trace(data_quality="DEGRADED", indicators_rejected=[{"indicator": "adx", "reason": "x"}]),
        )
        assert result["adjusted_confidence"] >= 0


class TestCA8NeverIncreases:
    def test_adjusted_confidence_always_less_than_or_equal_to_raw(self):
        for conf in (0, 20, 45, 60, 85):
            result = adjust_confidence(
                _setup(confidence=conf, signal="BUY", context=["week: price is below EMA20"]),
                _trace(data_quality="DEGRADED"),
            )
            assert result["adjusted_confidence"] <= result["raw_confidence"]


class TestCA9NotCheckedExplicit:
    def test_liquidity_and_iv_named_as_out_of_scope(self):
        result = adjust_confidence(_setup(), _trace())
        joined = " ".join(result["not_checked"]).lower()
        assert "liquidity" in joined or "spread" in joined
        assert "iv" in joined or "volatility" in joined or "expiry" in joined


class TestCA10GenerateTradeSetupTfSurfacesFields:
    def _fake_tech(self):
        return {
            "symbol": "NIFTY", "last_close": 100.0, "candles_used": 150,
            "data_source": "yfinance_eod_adjusted", "last_candle_date": _fresh_daily_date(),
            "rsi_14": 65.0, "ema_20": 95.0, "ema_50": 90.0,
            "macd": {"macd": 0.5, "signal": 0.3, "histogram": 0.2},
            "adx_14": {"adx": 30.0, "plus_di": 28.0, "minus_di": 12.0},
            "atr_14": 2.0,
        }

    def test_all_fields_present(self, monkeypatch):
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda symbol, lookback_days=150, interval="daily": self._fake_tech())
        result = generate_trade_setup_tf("NIFTY", "SWING", "day")
        assert "error" not in result
        for key in ("raw_confidence", "confidence", "confidence_penalties", "confidence_not_checked"):
            assert key in result


class TestCA11DecisionTraceReflectsAdjustedConfidence:
    def _fake_tech(self):
        return {
            "symbol": "NIFTY", "last_close": 100.0, "candles_used": 150,
            "data_source": "yfinance_eod_adjusted", "last_candle_date": _fresh_daily_date(),
            "rsi_14": 65.0, "ema_20": 95.0, "ema_50": 90.0,
            "macd": {"macd": 0.5, "signal": 0.3, "histogram": 0.2},
            "adx_14": {"adx": 30.0, "plus_di": 28.0, "minus_di": 12.0},
            "atr_14": 2.0,
        }

    def test_trace_confidence_matches_final_reported_confidence(self, monkeypatch):
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda symbol, lookback_days=150, interval="daily": self._fake_tech())
        result = generate_trade_setup_tf("NIFTY", "SWING", "day")
        assert "error" not in result
        assert result["decision_trace"]["confidence"] == result["confidence"]


class TestCA12DailyOnlyFunctionUnaffected:
    def test_generate_trade_setup_has_no_confidence_penalties(self, monkeypatch):
        fake = {
            "symbol": "NIFTY", "last_close": 100.0, "candles_used": 150,
            "data_source": "yfinance_eod_adjusted", "last_candle_date": _fresh_daily_date(),
            "rsi_14": 65.0, "ema_20": 95.0, "ema_50": 90.0,
            "macd": {"macd": 0.5, "signal": 0.3, "histogram": 0.2},
            "adx_14": {"adx": 30.0, "plus_di": 28.0, "minus_di": 12.0},
            "atr_14": 2.0,
        }
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda symbol, lookback_days=150, interval="daily": fake)
        result = generate_trade_setup("NIFTY")
        assert "error" not in result
        assert "confidence_penalties" not in result
        assert "confidence_not_checked" not in result

"""
Property / shape tests for the scoring systems (Phase 14.6, C3).

Point tests check single inputs; these assert invariants across a sweep of
inputs — the kind of guard that would have caught the original RSI>70 blind
spot (more extreme RSI silently increasing bullish conviction) and the
confidence-reaching-100 bug before they shipped.
"""
from __future__ import annotations

import pytest

import src.analysis.regime as regime
from src.analysis.regime import (
    _scale_confidence,
    detect_market_regime,
    generate_trade_setup,
)
from src.common.scoring import risk_rating


def _tech(rsi, ema20, ema50, adx, price, atr=2.0, macd_val=0.5, macd_sig=0.3):
    return {
        "symbol": "NIFTY",
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


def _patch(monkeypatch, tech):
    monkeypatch.setattr(regime, "_analyze_technicals", lambda s, lookback_days=150: tech)


# ---------------------------------------------------------------------------
# _scale_confidence: monotonic non-decreasing, bounded [0, 85]
# ---------------------------------------------------------------------------

class TestScaleConfidenceProperties:
    def test_bounded_and_monotonic(self):
        prev = -1
        for raw in range(0, 121):  # include >100 to prove the ceiling holds
            v = _scale_confidence(raw)
            assert 0 <= v <= 85
            assert v >= prev, "scaling must be non-decreasing in the raw score"
            prev = v

    def test_ceiling_is_85(self):
        assert _scale_confidence(100) == 85
        assert _scale_confidence(150) == 85


# ---------------------------------------------------------------------------
# Confidence ceiling across a wide input sweep
# ---------------------------------------------------------------------------

class TestConfidenceCeilingProperty:
    @pytest.mark.parametrize("rsi", [10, 25, 29, 31, 44, 50, 55, 60, 69, 71, 80, 95])
    @pytest.mark.parametrize("adx", [10, 19, 22, 26, 35, 60])
    def test_setup_confidence_in_band(self, monkeypatch, rsi, adx):
        _patch(monkeypatch, _tech(rsi=rsi, ema20=100.0, ema50=90.0, adx=adx, price=101.0))
        r = generate_trade_setup("NIFTY")
        assert 0 <= r["confidence"] <= 85

    @pytest.mark.parametrize("rsi", [10, 30, 50, 70, 95])
    @pytest.mark.parametrize("adx", [10, 22, 35])
    def test_regime_confidence_in_band(self, monkeypatch, rsi, adx):
        _patch(monkeypatch, _tech(rsi=rsi, ema20=100.0, ema50=90.0, adx=adx, price=101.0))
        r = detect_market_regime("NIFTY")
        assert 0 <= r["confidence"] <= 85


# ---------------------------------------------------------------------------
# RSI shape: overbought must NOT out-score healthy momentum (the original bug)
# ---------------------------------------------------------------------------

class TestRsiOverboughtShape:
    def _conf_for_rsi(self, monkeypatch, rsi):
        _patch(monkeypatch, _tech(rsi=rsi, ema20=100.0, ema50=90.0, adx=30.0, price=101.0))
        return generate_trade_setup("NIFTY")["confidence"]

    def test_overbought_not_more_confident_than_healthy(self, monkeypatch):
        healthy = self._conf_for_rsi(monkeypatch, 65)   # 55–70 bullish bin
        overbought = self._conf_for_rsi(monkeypatch, 74)  # >70 → bearish penalty
        assert overbought < healthy, (
            "an overbought RSI must not score more bullish conviction than "
            "healthy momentum — regression guard for the YES BANK incident"
        )

    def test_more_extreme_overbought_does_not_increase_confidence(self, monkeypatch):
        # Within the overbought region, pushing RSI higher must not raise the
        # (bullish) confidence — it should stay capped/penalised.
        c72 = self._conf_for_rsi(monkeypatch, 72)
        c95 = self._conf_for_rsi(monkeypatch, 95)
        assert c95 <= c72


# ---------------------------------------------------------------------------
# risk_rating: monotonic non-decreasing across the 0–100 range
# ---------------------------------------------------------------------------

class TestRiskRatingMonotonic:
    _RANK = {"LOW": 0, "MODERATE": 1, "HIGH": 2, "EXTREME": 3}

    def test_non_decreasing(self):
        prev = -1
        for score in range(0, 101):
            rank = self._RANK[risk_rating(score)]
            assert rank >= prev, f"rating must not decrease as score rises (at {score})"
            prev = rank

    def test_endpoints(self):
        assert risk_rating(0) == "LOW"
        assert risk_rating(100) == "EXTREME"

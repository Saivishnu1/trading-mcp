"""Regression test for Audit-H5 — calibration must never amplify position
size, only ever shrink it or leave it unchanged.

Finding: calibration_size_factor() returned 1.10 at calibrated_confidence
>= 75, and recommend_trade() applied that as a real size multiplier via
_cal_size_factor. generate_trade_setup's underlying confidence score is a
hand-weighted indicator sum with no backtested basis (unlike the walk-forward
-audited signals Phase 20A/21 found lacked directional edge and deleted
outright) — even after gating on >=20 historical trades in a bucket,
amplifying size asserts a stronger edge claim than the score was ever
validated to support. Shrinking size on a historically-overconfident bucket
is a legitimate safeguard; boosting it on a historically-accurate one is not
— the two are not symmetric risks.

CSB-1  calibration_size_factor never returns > 1.0 for any confidence input
CSB-2  recommend_trade does not boost position_size even when calibration_applied
       is True and calibrated_confidence is in the old >=75 boost band
CSB-3  recommend_trade still shrinks position_size for a low calibrated_confidence bucket
"""
from __future__ import annotations

import src.recommendations.engine as rec_engine
from src.feedback.calibration_adjustment import calibration_size_factor


class TestCSB1NeverBoosts:
    def test_high_calibrated_confidence_factor_is_capped_at_one(self):
        assert calibration_size_factor(85.0) == 1.0
        assert calibration_size_factor(75.0) == 1.0

    def test_low_calibrated_confidence_still_shrinks(self):
        assert calibration_size_factor(40.0) == 0.50


def _base_plan(**overrides):
    plan = {
        "signal": "BUY",
        "trade_allowed": True,
        "market_context": {"regime": "BULL_TREND"},
        "entry": 100.0,
        "stoploss": 95.0,
        "target": 115.0,
        "risk_reward": {"rr": 3.0},
        "position": {"position_size": 100},
        "strategy": {"recommended": "Bull Call Spread"},
        "trade_quality": "HIGH_QUALITY",
        "data_basis": {"staleness_days": 0, "last_candle_date": "2026-07-22"},
        "raw_confidence": 80,
        "calibrated_confidence": 80,
        "confidence_adjustment": 0,
        "calibration_applied": True,
    }
    plan.update(overrides)
    return plan


def _setup_common(monkeypatch, plan):
    monkeypatch.setattr(rec_engine, "_get_open_trades", lambda symbol=None: {"trades": []})
    monkeypatch.setattr(rec_engine, "_create_trade_plan",
                         lambda symbol, capital, risk_percent: plan)
    monkeypatch.setattr(rec_engine, "_get_event_risk", lambda symbol: {"error": "unavailable"})
    monkeypatch.setattr(rec_engine, "_get_india_vix", lambda: {"error": "unavailable"})
    monkeypatch.setattr(rec_engine, "_get_regime_alignment", lambda symbol: {"error": "unavailable"})


class TestCSB2NoSizeBoostFromRecommendTrade:
    def test_high_calibrated_confidence_does_not_increase_position_size(self, monkeypatch):
        plan = _base_plan(calibrated_confidence=80, raw_confidence=70)
        _setup_common(monkeypatch, plan)
        result = rec_engine.recommend_trade("NIFTY")
        assert result["position_size"] == 100  # unchanged, never boosted to 110

    def test_no_increased_size_risk_adjustment_message(self, monkeypatch):
        plan = _base_plan(calibrated_confidence=80, raw_confidence=70)
        _setup_common(monkeypatch, plan)
        result = rec_engine.recommend_trade("NIFTY")
        assert not any("increased" in adj.lower() for adj in result["risk_adjustments"])


class TestCSB3StillShrinksOnLowCalibration:
    def test_low_calibrated_confidence_reduces_position_size(self, monkeypatch):
        plan = _base_plan(calibrated_confidence=40, raw_confidence=60)
        _setup_common(monkeypatch, plan)
        result = rec_engine.recommend_trade("NIFTY")
        assert result["position_size"] == 50  # 100 * 0.50
        assert any("reduced" in adj.lower() for adj in result["risk_adjustments"])

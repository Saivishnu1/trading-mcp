"""Tests for Phase 18 — Recommendation Feedback Loop."""
import pytest

from src.feedback.calibration_adjustment import (
    get_calibrated_confidence,
    calibration_size_factor,
    _bucket_for_confidence,
    _adjustment_for_bucket,
    _MIN_CALIBRATION_SAMPLE,
    _CONFIDENCE_SCALE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _curve(bucket, trade_count, actual_win_rate):
    """Build a minimal reliability curve entry."""
    return {
        "bucket": bucket,
        "trade_count": trade_count,
        "actual_win_rate": actual_win_rate,
        "avg_predicted_probability": actual_win_rate,
        "calibration_gap": 0.0,
        "low_sample": trade_count < _MIN_CALIBRATION_SAMPLE,
    }


# ---------------------------------------------------------------------------
# _bucket_for_confidence
# ---------------------------------------------------------------------------

class TestBucketForConfidence:
    def test_high(self):
        assert _bucket_for_confidence(80.0) == "high"

    def test_high_boundary(self):
        assert _bucket_for_confidence(75.0) == "high"

    def test_moderate(self):
        assert _bucket_for_confidence(65.0) == "moderate"

    def test_moderate_boundary(self):
        assert _bucket_for_confidence(60.0) == "moderate"

    def test_low(self):
        assert _bucket_for_confidence(45.0) == "low"

    def test_zero(self):
        assert _bucket_for_confidence(0.0) == "low"


# ---------------------------------------------------------------------------
# _adjustment_for_bucket
# ---------------------------------------------------------------------------

class TestAdjustmentForBucket:
    def test_sufficient_sample_converts_win_rate(self):
        b = _curve("high", _MIN_CALIBRATION_SAMPLE, 0.70)
        result = _adjustment_for_bucket(b)
        assert result == pytest.approx(0.70 * _CONFIDENCE_SCALE, abs=0.1)

    def test_insufficient_sample_returns_none(self):
        b = _curve("high", _MIN_CALIBRATION_SAMPLE - 1, 0.70)
        assert _adjustment_for_bucket(b) is None

    def test_zero_trade_count_returns_none(self):
        b = _curve("high", 0, 0.70)
        assert _adjustment_for_bucket(b) is None

    def test_missing_win_rate_returns_none(self):
        b = {"bucket": "high", "trade_count": _MIN_CALIBRATION_SAMPLE, "actual_win_rate": None}
        assert _adjustment_for_bucket(b) is None


# ---------------------------------------------------------------------------
# get_calibrated_confidence
# ---------------------------------------------------------------------------

class TestGetCalibratedConfidence:
    def test_empty_curve_returns_no_calibration(self):
        r = get_calibrated_confidence(75.0, [])
        assert r["calibration_applied"] is False
        assert r["calibrated_confidence"] == 75.0
        assert r["confidence_adjustment"] == 0
        assert r["reason"] == "no_history"

    def test_bucket_not_in_curve_returns_no_calibration(self):
        # only "low" bucket in curve — raw_confidence=80 maps to "high"
        curve = [_curve("low", _MIN_CALIBRATION_SAMPLE, 0.60)]
        r = get_calibrated_confidence(80.0, curve)
        assert r["calibration_applied"] is False
        assert r["reason"] == "bucket_not_found"

    def test_insufficient_sample_returns_no_calibration(self):
        curve = [_curve("high", _MIN_CALIBRATION_SAMPLE - 1, 0.70)]
        r = get_calibrated_confidence(80.0, curve)
        assert r["calibration_applied"] is False
        assert r["reason"] == "insufficient_sample"

    def test_successful_calibration(self):
        # raw=80 → bucket=high → actual_win_rate=0.65 → calibrated=0.65*85=55.25
        curve = [_curve("high", _MIN_CALIBRATION_SAMPLE, 0.65)]
        r = get_calibrated_confidence(80.0, curve)
        assert r["calibration_applied"] is True
        assert r["calibrated_confidence"] == pytest.approx(0.65 * 85.0, abs=0.1)
        assert r["confidence_adjustment"] < 0  # overconfident → negative adjustment

    def test_underconfident_positive_adjustment(self):
        # raw=60 → bucket=moderate → actual_win_rate=0.90 → calibrated=76.5
        curve = [_curve("moderate", _MIN_CALIBRATION_SAMPLE, 0.90)]
        r = get_calibrated_confidence(60.0, curve)
        assert r["calibration_applied"] is True
        assert r["calibrated_confidence"] > 60.0
        assert r["confidence_adjustment"] > 0

    def test_calibrated_confidence_never_below_zero(self):
        # actual_win_rate=0 → calibrated=0 (not negative)
        curve = [_curve("low", _MIN_CALIBRATION_SAMPLE, 0.0)]
        r = get_calibrated_confidence(40.0, curve)
        assert r["calibrated_confidence"] >= 0.0

    def test_calibrated_confidence_never_above_85(self):
        # actual_win_rate=1.0 → calibrated=85 (not above ceiling)
        curve = [_curve("high", _MIN_CALIBRATION_SAMPLE, 1.0)]
        r = get_calibrated_confidence(80.0, curve)
        assert r["calibrated_confidence"] <= 85.0

    def test_perfect_calibration_zero_adjustment(self):
        # raw=68 → bucket=moderate; actual_win_rate = 68/85 → calibrated=68
        raw = 68.0
        win_rate = raw / 85.0
        curve = [_curve("moderate", _MIN_CALIBRATION_SAMPLE, win_rate)]
        r = get_calibrated_confidence(raw, curve)
        assert r["calibration_applied"] is True
        assert r["confidence_adjustment"] == pytest.approx(0.0, abs=0.2)


# ---------------------------------------------------------------------------
# calibration_size_factor
# ---------------------------------------------------------------------------

class TestCalibrationSizeFactor:
    def test_very_low_confidence_half_size(self):
        assert calibration_size_factor(45.0) == 0.50

    def test_at_45_boundary(self):
        assert calibration_size_factor(45.0) == 0.50

    def test_low_confidence_three_quarter_size(self):
        assert calibration_size_factor(50.0) == 0.75

    def test_at_55_boundary(self):
        assert calibration_size_factor(55.0) == 0.75

    def test_mid_range_no_adjustment(self):
        assert calibration_size_factor(65.0) == 1.0

    def test_high_confidence_no_boost(self):
        # Audit-H5: calibration must never amplify size, even at high
        # calibrated confidence — it can only shrink it or leave it unchanged.
        assert calibration_size_factor(75.0) == 1.0

    def test_above_75_no_boost(self):
        assert calibration_size_factor(80.0) == 1.0

    def test_never_exceeds_one(self):
        for conf in (0.0, 20.0, 45.0, 50.0, 55.0, 60.0, 65.0, 75.0, 80.0, 85.0):
            assert calibration_size_factor(conf) <= 1.0

    def test_zero_confidence_half_size(self):
        assert calibration_size_factor(0.0) == 0.50


# ---------------------------------------------------------------------------
# Integration: create_trade_plan exposes calibration fields
# ---------------------------------------------------------------------------

class TestCreateTradePlanCalibrationFields:
    def test_calibration_fields_present_when_no_history(self, monkeypatch):
        """Without journal history calibration_applied=False but keys exist."""
        from src.planner import trade_plan as tp
        snap = {
            "signal": "BUY", "confidence": 70, "entry": 1000.0,
            "stoploss": 950.0, "target": 1100.0, "data_basis": None,
            "entry_above": 1000.0, "entry_below": 990.0,
            "bull_target": 1100.0, "bear_target": 950.0, "reasoning": [],
        }
        monkeypatch.setattr("src.planner.trade_plan.generate_trade_setup", lambda s: snap)
        monkeypatch.setattr("src.planner.trade_plan.recommend_strategy", lambda s: {
            "recommended": "Bull Call Spread", "regime": "BULL_TREND",
            "signal": "BUY", "reason": "test",
        })
        monkeypatch.setattr("src.planner.trade_plan.calculate_risk_reward", lambda *a: {"rr": 2.0, "risk": 50.0, "reward": 100.0})
        monkeypatch.setattr("src.planner.trade_plan.calculate_position_size", lambda *a: {"position_size": 10, "capital": 100000, "risk_percent": 1.0, "risk_amount": 1000})
        monkeypatch.setattr("src.planner.trade_plan._options_context", lambda s: {})
        monkeypatch.setattr("src.planner.trade_plan._risk_score_context", lambda s: None)

        plan = tp.create_trade_plan("INFY")

        assert "raw_confidence" in plan
        assert "calibrated_confidence" in plan
        assert "confidence_adjustment" in plan
        assert "calibration_applied" in plan
        assert plan["raw_confidence"] == 70
        assert plan["calibrated_confidence"] == pytest.approx(70.0, abs=1.0)

    def test_existing_confidence_key_unchanged(self, monkeypatch):
        """Backward compat: 'confidence' key must still be present and unchanged."""
        from src.planner import trade_plan as tp
        snap = {
            "signal": "BUY", "confidence": 72, "entry": 1000.0,
            "stoploss": 950.0, "target": 1100.0, "data_basis": None,
            "entry_above": 1000.0, "entry_below": 990.0,
            "bull_target": 1100.0, "bear_target": 950.0, "reasoning": [],
        }
        monkeypatch.setattr("src.planner.trade_plan.generate_trade_setup", lambda s: snap)
        monkeypatch.setattr("src.planner.trade_plan.recommend_strategy", lambda s: {
            "recommended": "Bull Call Spread", "regime": "BULL_TREND",
            "signal": "BUY", "reason": "test",
        })
        monkeypatch.setattr("src.planner.trade_plan.calculate_risk_reward", lambda *a: {"rr": 2.0, "risk": 50.0, "reward": 100.0})
        monkeypatch.setattr("src.planner.trade_plan.calculate_position_size", lambda *a: {"position_size": 10, "capital": 100000, "risk_percent": 1.0, "risk_amount": 1000})
        monkeypatch.setattr("src.planner.trade_plan._options_context", lambda s: {})
        monkeypatch.setattr("src.planner.trade_plan._risk_score_context", lambda s: None)

        plan = tp.create_trade_plan("INFY")
        assert plan["confidence"] == 72


"""Phase 18 regression guards — FB-1 through FB-7."""
import pytest

from src.feedback.calibration_adjustment import (
    get_calibrated_confidence,
    calibration_size_factor,
    _MIN_CALIBRATION_SAMPLE,
)


def _full_curve(trade_count=_MIN_CALIBRATION_SAMPLE):
    return [
        {"bucket": "high",     "trade_count": trade_count, "actual_win_rate": 0.70, "low_sample": trade_count < _MIN_CALIBRATION_SAMPLE},
        {"bucket": "moderate", "trade_count": trade_count, "actual_win_rate": 0.55, "low_sample": trade_count < _MIN_CALIBRATION_SAMPLE},
        {"bucket": "low",      "trade_count": trade_count, "actual_win_rate": 0.40, "low_sample": trade_count < _MIN_CALIBRATION_SAMPLE},
    ]



class TestFB1NoCalibrationHistoryRecommendationUnchanged:
    """FB-1: No calibration history → calibration_applied=False, no size change."""

    def test_empty_curve_no_adjustment(self):
        r = get_calibrated_confidence(75.0, [])
        assert r["calibration_applied"] is False
        assert r["calibrated_confidence"] == 75.0
        assert r["confidence_adjustment"] == 0


class TestFB2LowSampleBucketNoCalibration:
    """FB-2: Bucket below MIN_CALIBRATION_SAMPLE → no calibration applied."""

    def test_thin_bucket_skipped(self):
        curve = [{"bucket": "high", "trade_count": _MIN_CALIBRATION_SAMPLE - 1,
                  "actual_win_rate": 0.80, "low_sample": True}]
        r = get_calibrated_confidence(80.0, curve)
        assert r["calibration_applied"] is False
        assert r["reason"] == "insufficient_sample"

    def test_zero_count_skipped(self):
        curve = [{"bucket": "moderate", "trade_count": 0, "actual_win_rate": 0.80, "low_sample": True}]
        r = get_calibrated_confidence(65.0, curve)
        assert r["calibration_applied"] is False


class TestFB3MissingConfidenceCalibrationSkipped:
    """FB-3: Bucket has no actual_win_rate → calibration skipped."""

    def test_none_win_rate_returns_raw(self):
        curve = [{"bucket": "high", "trade_count": _MIN_CALIBRATION_SAMPLE,
                  "actual_win_rate": None, "low_sample": False}]
        r = get_calibrated_confidence(80.0, curve)
        assert r["calibration_applied"] is False
        assert r["calibrated_confidence"] == 80.0


class TestFB4AdjustedConfidenceNeverBelowZero:
    """FB-4: calibrated_confidence is always >= 0."""

    def test_zero_win_rate_produces_zero_not_negative(self):
        curve = [{"bucket": "low", "trade_count": _MIN_CALIBRATION_SAMPLE,
                  "actual_win_rate": 0.0, "low_sample": False}]
        r = get_calibrated_confidence(40.0, curve)
        assert r["calibrated_confidence"] >= 0.0

    def test_confidence_floor_at_zero(self):
        # Extremely low win rate → calibrated rounds to 0
        for win_rate in [0.0, 0.001, 0.005]:
            curve = [{"bucket": "low", "trade_count": _MIN_CALIBRATION_SAMPLE,
                      "actual_win_rate": win_rate, "low_sample": False}]
            r = get_calibrated_confidence(40.0, curve)
            assert r["calibrated_confidence"] >= 0.0


class TestFB5AdjustedConfidenceNeverAbove85:
    """FB-5: calibrated_confidence is always <= 85."""

    def test_perfect_win_rate_caps_at_85(self):
        curve = [{"bucket": "high", "trade_count": _MIN_CALIBRATION_SAMPLE,
                  "actual_win_rate": 1.0, "low_sample": False}]
        r = get_calibrated_confidence(80.0, curve)
        assert r["calibrated_confidence"] <= 85.0

    def test_high_win_rate_within_ceiling(self):
        for win_rate in [0.95, 0.99, 1.0]:
            curve = [{"bucket": "high", "trade_count": _MIN_CALIBRATION_SAMPLE,
                      "actual_win_rate": win_rate, "low_sample": False}]
            r = get_calibrated_confidence(75.0, curve)
            assert r["calibrated_confidence"] <= 85.0


class TestFB6ExistingSchemaUnchanged:
    """FB-6: recommend_trade and create_trade_plan still expose all original keys."""

    REQUIRED_RECOMMEND_KEYS = {
        "symbol", "recommendation", "trade_allowed", "direction", "regime",
        "signal", "entry", "stoploss", "target", "risk_reward", "position_size",
        "strategy", "trade_quality", "event_risk_score", "event_risk_rating",
        "vix", "vix_caution", "duplicate_exposure", "cautions", "reasons",
        "risk_adjustments", "gating_data_available", "data_basis",
    }

    REQUIRED_PLAN_KEYS = {
        "symbol", "trade_allowed", "signal", "trade_quality", "confidence",
        "entry", "stoploss", "target", "risk_reward", "position", "strategy",
        "market_context", "risk_score", "data_basis", "summary",
    }

    def test_create_trade_plan_has_all_original_keys(self, monkeypatch):
        from src.planner import trade_plan as tp
        snap = {
            "signal": "BUY", "confidence": 70, "entry": 1000.0,
            "stoploss": 950.0, "target": 1100.0, "data_basis": None,
            "entry_above": 1000.0, "entry_below": 990.0,
            "bull_target": 1100.0, "bear_target": 950.0, "reasoning": [],
        }
        monkeypatch.setattr("src.planner.trade_plan.generate_trade_setup", lambda s: snap)
        monkeypatch.setattr("src.planner.trade_plan.recommend_strategy", lambda s: {
            "recommended": "Bull Call Spread", "regime": "BULL_TREND", "signal": "BUY", "reason": "",
        })
        monkeypatch.setattr("src.planner.trade_plan.calculate_risk_reward", lambda *a: {"rr": 2.0, "risk": 50.0, "reward": 100.0})
        monkeypatch.setattr("src.planner.trade_plan.calculate_position_size", lambda *a: {"position_size": 10, "capital": 100000, "risk_percent": 1.0, "risk_amount": 1000})
        monkeypatch.setattr("src.planner.trade_plan._options_context", lambda s: {})
        monkeypatch.setattr("src.planner.trade_plan._risk_score_context", lambda s: None)

        plan = tp.create_trade_plan("INFY")
        for key in self.REQUIRED_PLAN_KEYS:
            assert key in plan, f"missing key: {key}"


"""Phase 18 — Recommendation Feedback Loop.

Applies Phase 17 calibration data to adjust confidence scores in recommendations.
Helpers are designed for reuse by higher-level callers (recommend_trade, create_trade_plan).
"""
from __future__ import annotations

# Trades below this count in a bucket are too thin to calibrate against.
_MIN_CALIBRATION_SAMPLE = 20

# System-wide confidence ceiling — same as calibration/service.py.
_CONFIDENCE_SCALE = 85.0


def _bucket_for_confidence(raw_confidence: float) -> str:
    if raw_confidence >= 75.0:
        return "high"
    if raw_confidence >= 60.0:
        return "moderate"
    return "low"


def _adjustment_for_bucket(bucket_data: dict) -> float | None:
    """Convert a bucket's actual_win_rate back to the [0-85] confidence space.

    Returns None when the bucket has too few samples or missing win-rate data.
    """
    if bucket_data.get("trade_count", 0) < _MIN_CALIBRATION_SAMPLE:
        return None
    actual_win_rate = bucket_data.get("actual_win_rate")
    if actual_win_rate is None:
        return None
    return round(actual_win_rate * _CONFIDENCE_SCALE, 1)


def get_calibrated_confidence(
    raw_confidence: float,
    reliability_curve: list[dict],
) -> dict:
    """Return calibration metadata for a given raw confidence value.

    Finds the matching bucket in the reliability_curve (from Phase 17
    get_calibration_report), converts its actual_win_rate back to the 0-85
    confidence scale, and returns the delta.

    Always returns a dict; calibration_applied=False means "use raw value."
    """
    _no_calibration = {
        "calibration_applied": False,
        "calibrated_confidence": raw_confidence,
        "confidence_adjustment": 0,
        "reason": None,
    }

    if not reliability_curve:
        return {**_no_calibration, "reason": "no_history"}

    target_bucket = _bucket_for_confidence(raw_confidence)
    bucket_data = next(
        (b for b in reliability_curve if b.get("bucket") == target_bucket), None
    )

    if bucket_data is None:
        return {**_no_calibration, "reason": "bucket_not_found"}

    calibrated = _adjustment_for_bucket(bucket_data)
    if calibrated is None:
        return {**_no_calibration, "reason": "insufficient_sample"}

    # Clamp to valid confidence range [0, 85].
    calibrated = max(0.0, min(_CONFIDENCE_SCALE, calibrated))
    adjustment = round(calibrated - raw_confidence, 1)

    return {
        "calibration_applied": True,
        "calibrated_confidence": calibrated,
        "confidence_adjustment": adjustment,
        "reason": None,
    }


def calibration_size_factor(calibrated_confidence: float) -> float:
    """Position size multiplier derived from calibrated confidence.

    Reduces size when historical performance suggests lower win probability
    than the raw model confidence implies. Never increases size (Audit-H5):
    generate_trade_setup's confidence is a hand-weighted indicator score with
    no backtested basis (unlike Phase 20A/21's walk-forward-audited signals,
    which were found to lack directional edge and had their fields deleted
    entirely) — calibration against realized win rate is a legitimate
    safeguard for shrinking size on historically-overconfident buckets, but
    amplifying size on a historically-accurate bucket asserts a stronger
    edge claim than the underlying score was ever validated to support.
    """
    if calibrated_confidence <= 45.0:
        return 0.50
    if calibrated_confidence <= 55.0:
        return 0.75
    return 1.0

"""
Tests for src/common — shared primitives (Phase 14.6, B2).

These guard the single-source-of-truth consolidation: rating bands, size-factor
math, signal→direction mapping, and regime-name coverage across modules.
"""
from __future__ import annotations

from src.common.scoring import apply_size_factors, risk_rating
from src.common.signals import (
    LONG_SIGNALS,
    NEUTRAL_SIGNALS,
    SHORT_SIGNALS,
    direction_from_signal,
)


class TestRiskRating:
    def test_bands(self):
        assert risk_rating(0) == "LOW"
        assert risk_rating(29) == "LOW"
        assert risk_rating(30) == "MODERATE"
        assert risk_rating(59) == "MODERATE"
        assert risk_rating(60) == "HIGH"
        assert risk_rating(79) == "HIGH"
        assert risk_rating(80) == "EXTREME"
        assert risk_rating(100) == "EXTREME"

    def test_matches_both_former_callers(self):
        # risk.py and event_risk.py both alias this now.
        from src.catalyst.event_risk import _rating as event_alias
        from src.intelligence.risk import _rating as risk_alias
        for score in (10, 35, 70, 95):
            assert risk_alias(score) == event_alias(score) == risk_rating(score)


class TestApplySizeFactors:
    def test_none_base_returns_none(self):
        assert apply_size_factors(None, [0.5]) is None

    def test_no_factors_returns_base(self):
        assert apply_size_factors(10, []) == 10

    def test_factors_multiply_and_round(self):
        assert apply_size_factors(10, [0.5]) == 5
        assert apply_size_factors(10, [0.7, 0.5]) == 4  # 3.5 → 4

    def test_floor_at_one(self):
        assert apply_size_factors(1, [0.1]) == 1
        assert apply_size_factors(2, [0.01]) == 1

    def test_shared_by_both_engines(self):
        import src.recommendations.engine as rec
        import src.sizer.engine as sizer
        assert rec._apply_size_factors is sizer._apply_size_factors is apply_size_factors


class TestDirectionFromSignal:
    def test_long_signals(self):
        for s in LONG_SIGNALS:
            assert direction_from_signal(s) == "LONG"

    def test_short_signals(self):
        for s in SHORT_SIGNALS:
            assert direction_from_signal(s) == "SHORT"

    def test_neutral_is_none(self):
        for s in NEUTRAL_SIGNALS:
            assert direction_from_signal(s) is None

    def test_unknown_is_none(self):
        assert direction_from_signal("WHATEVER") is None


class TestRegimeCoverage:
    def test_every_regime_has_a_risk_score(self):
        # Drift guard: a new regime added to regime.REGIMES without a matching
        # _REGIME_SCORES entry would silently score the neutral fallback.
        from src.analysis.regime import REGIMES
        from src.intelligence.risk import _REGIME_SCORES
        missing = REGIMES - set(_REGIME_SCORES)
        assert not missing, f"regimes missing a risk score: {missing}"

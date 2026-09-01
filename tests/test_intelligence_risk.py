"""Tests for src/intelligence/risk.py"""
from __future__ import annotations

import time

# ---------------------------------------------------------------------------
# PCR score lookup (B3: keyed on stable code, not display prose)
# ---------------------------------------------------------------------------

class TestPcrScore:
    def test_bullish_code(self):
        from src.intelligence.risk import _pcr_score
        assert _pcr_score("BULLISH") == 10

    def test_mildly_bullish_code(self):
        from src.intelligence.risk import _pcr_score
        assert _pcr_score("MILDLY_BULLISH") == 25

    def test_neutral_bearish_code(self):
        from src.intelligence.risk import _pcr_score
        assert _pcr_score("NEUTRAL_BEARISH") == 55

    def test_bearish_code(self):
        from src.intelligence.risk import _pcr_score
        assert _pcr_score("BEARISH") == 85

    def test_insufficient_data_code(self):
        from src.intelligence.risk import _pcr_score
        assert _pcr_score("INSUFFICIENT_DATA") == 50

    def test_unknown_code_returns_neutral(self):
        from src.intelligence.risk import _pcr_score
        assert _pcr_score("SOMETHING_ELSE") == 50

    def test_codes_match_analytics_output(self):
        # B3 contract: the codes risk.py keys on are exactly the ones analytics emits.
        from src.intelligence.risk import _PCR_CODE_RISK
        from src.options.analytics import _pcr_code
        for pcr in (None, 1.5, 1.1, 0.8, 0.5):
            assert _pcr_code(pcr) in _PCR_CODE_RISK

    def test_score_decoupled_from_interpretation_prose(self):
        # Reword the display prose → score must NOT change (the whole point of B3).
        from src.intelligence.risk import _pcr_score
        from src.options.analytics import _pcr_code
        assert _pcr_score(_pcr_code(0.5)) == 85  # bearish, regardless of prose wording


# ---------------------------------------------------------------------------
# Event score
# ---------------------------------------------------------------------------

class TestEventScore:
    def _evt(self, days, impact="HIGH"):
        return {"days_until": days, "impact": impact, "date": "2026-01-01",
                "event_type": "TEST", "description": "x"}

    def test_no_high_impact_returns_zero(self):
        from src.intelligence.risk import _event_score
        events = {"events": [self._evt(2, "MEDIUM")]}
        assert _event_score(events) == 0

    def test_empty_events_returns_zero(self):
        from src.intelligence.risk import _event_score
        assert _event_score({"events": []}) == 0

    def test_tomorrow_returns_100(self):
        from src.intelligence.risk import _event_score
        events = {"events": [self._evt(1)]}
        assert _event_score(events) == 100

    def test_two_days_returns_80(self):
        from src.intelligence.risk import _event_score
        events = {"events": [self._evt(2)]}
        assert _event_score(events) == 80

    def test_five_days_returns_50(self):
        from src.intelligence.risk import _event_score
        events = {"events": [self._evt(5)]}
        assert _event_score(events) == 50

    def test_far_away_returns_20(self):
        from src.intelligence.risk import _event_score
        events = {"events": [self._evt(10)]}
        assert _event_score(events) == 20


# ---------------------------------------------------------------------------
# Rating thresholds
# ---------------------------------------------------------------------------

class TestRating:
    def test_low(self):
        from src.intelligence.risk import _rating
        assert _rating(20) == "LOW"

    def test_moderate(self):
        from src.intelligence.risk import _rating
        assert _rating(45) == "MODERATE"

    def test_high(self):
        from src.intelligence.risk import _rating
        assert _rating(70) == "HIGH"

    def test_extreme(self):
        from src.intelligence.risk import _rating
        assert _rating(90) == "EXTREME"

    def test_boundaries(self):
        from src.intelligence.risk import _rating
        assert _rating(29) == "LOW"
        assert _rating(30) == "MODERATE"
        assert _rating(59) == "MODERATE"
        assert _rating(60) == "HIGH"
        assert _rating(79) == "HIGH"
        assert _rating(80) == "EXTREME"


# ---------------------------------------------------------------------------
# get_market_risk_score — full integration with mocked components
# ---------------------------------------------------------------------------

class TestGetMarketRiskScore:
    def _patch_all(self, monkeypatch, vix_score=45, event_score=0, pcr_score=25, regime_score=25):
        import src.intelligence.risk as risk_mod

        with risk_mod._LOCK:
            risk_mod._CACHE.clear()

        monkeypatch.setattr(
            risk_mod, "_vix_component",
            lambda: (vix_score, f"VIX stub → {vix_score}"),
        )
        monkeypatch.setattr(
            risk_mod, "_event_component",
            lambda: (event_score, f"Events stub → {event_score}"),
        )
        monkeypatch.setattr(
            risk_mod, "_pcr_component",
            lambda sym: (pcr_score, f"PCR stub → {pcr_score}"),
        )
        monkeypatch.setattr(
            risk_mod, "_regime_component",
            lambda sym: (regime_score, f"Regime stub → {regime_score}"),
        )
        # get_upcoming_events used for recommendation — return empty
        monkeypatch.setattr(
            risk_mod, "get_upcoming_events",
            lambda **kw: {"events": [], "nearest_high_impact_days": None},
        )

    def test_returns_expected_keys(self, monkeypatch):
        import src.intelligence.risk as risk_mod
        self._patch_all(monkeypatch)
        result = risk_mod.get_market_risk_score("NIFTY")
        for key in ("symbol", "score", "rating", "factors", "recommendation", "inputs"):
            assert key in result, f"missing key: {key}"

    def test_score_clamped_to_100(self, monkeypatch):
        import src.intelligence.risk as risk_mod
        self._patch_all(monkeypatch, vix_score=100, event_score=100, pcr_score=100, regime_score=100)
        result = risk_mod.get_market_risk_score("NIFTY")
        assert result["score"] == 100

    def test_score_clamped_to_zero(self, monkeypatch):
        import src.intelligence.risk as risk_mod
        self._patch_all(monkeypatch, vix_score=0, event_score=0, pcr_score=0, regime_score=0)
        result = risk_mod.get_market_risk_score("NIFTY")
        assert result["score"] == 0

    def test_weighted_score_calculation(self, monkeypatch):
        import src.intelligence.risk as risk_mod
        # Known values: 40*0.35 + 60*0.30 + 20*0.20 + 80*0.15 = 14+18+4+12 = 48
        self._patch_all(monkeypatch, vix_score=40, event_score=60, pcr_score=20, regime_score=80)
        result = risk_mod.get_market_risk_score("NIFTY")
        assert result["score"] == 48

    def test_four_factors_returned(self, monkeypatch):
        import src.intelligence.risk as risk_mod
        self._patch_all(monkeypatch)
        result = risk_mod.get_market_risk_score("NIFTY")
        assert len(result["factors"]) == 4

    def test_inputs_contain_component_scores(self, monkeypatch):
        import src.intelligence.risk as risk_mod
        self._patch_all(monkeypatch, vix_score=30, event_score=50, pcr_score=25, regime_score=40)
        result = risk_mod.get_market_risk_score("NIFTY")
        assert result["inputs"]["vix_score"] == 30
        assert result["inputs"]["event_score"] == 50

    def test_caching(self, monkeypatch):
        import src.intelligence.risk as risk_mod
        self._patch_all(monkeypatch)
        r1 = risk_mod.get_market_risk_score("NIFTY")

        # Inject stale-looking cache entry
        with risk_mod._LOCK:
            risk_mod._CACHE["risk_NIFTY"] = ({"score": 99, "cached": True}, time.monotonic())

        r2 = risk_mod.get_market_risk_score("NIFTY")
        assert r2.get("cached") is True  # hit cache

    def test_event_warning_in_recommendation(self, monkeypatch):
        import src.intelligence.risk as risk_mod
        with risk_mod._LOCK:
            risk_mod._CACHE.clear()

        monkeypatch.setattr(risk_mod, "_vix_component", lambda: (15, "VIX LOW"))
        monkeypatch.setattr(risk_mod, "_event_component", lambda: (100, "Event tomorrow"))
        monkeypatch.setattr(risk_mod, "_pcr_component", lambda sym: (25, "PCR ok"))
        monkeypatch.setattr(risk_mod, "_regime_component", lambda sym: (25, "Regime ok"))
        monkeypatch.setattr(
            risk_mod, "get_upcoming_events",
            lambda **kw: {
                "events": [{
                    "days_until": 1,
                    "impact": "HIGH",
                    "description": "RBI MPC Decision",
                    "date": "2026-06-18",
                    "event_type": "RBI_MPC",
                }],
                "nearest_high_impact_days": 1,
            },
        )

        result = risk_mod.get_market_risk_score("NIFTY")
        assert "RBI MPC Decision" in result["recommendation"] or "1 day" in result["recommendation"]


# ---------------------------------------------------------------------------
# TestRiskScoreDegradation — A3 (Phase 14.6)
# ---------------------------------------------------------------------------

class TestRiskScoreDegradation:
    """
    A3: a score built from neutral fallbacks must report reduced confidence and
    is_degraded=True, instead of presenting a fabricated MODERATE as reliable.
    """

    def _clear(self, risk_mod):
        with risk_mod._LOCK:
            risk_mod._CACHE.clear()

    def test_all_components_ok_confidence_one(self, monkeypatch):
        import src.intelligence.risk as risk_mod
        self._clear(risk_mod)
        monkeypatch.setattr(risk_mod, "_vix_component", lambda: (15, "vix", True))
        monkeypatch.setattr(risk_mod, "_event_component", lambda: (0, "ev", True))
        monkeypatch.setattr(risk_mod, "_pcr_component", lambda s: (25, "pcr", True))
        monkeypatch.setattr(risk_mod, "_regime_component", lambda s: (25, "rg", True))
        monkeypatch.setattr(risk_mod, "get_upcoming_events", lambda **k: {"events": []})

        result = risk_mod.get_market_risk_score("NIFTY")
        assert result["confidence"] == 1.0
        assert result["is_degraded"] is False
        assert result["degraded_components"] == []

    def test_pcr_and_regime_degraded_lowers_confidence(self, monkeypatch):
        import src.intelligence.risk as risk_mod
        self._clear(risk_mod)
        monkeypatch.setattr(risk_mod, "_vix_component", lambda: (15, "vix", True))
        monkeypatch.setattr(risk_mod, "_event_component", lambda: (0, "ev", True))
        monkeypatch.setattr(risk_mod, "_pcr_component", lambda s: (50, "pcr down", False))
        monkeypatch.setattr(risk_mod, "_regime_component", lambda s: (50, "rg down", False))
        monkeypatch.setattr(risk_mod, "get_upcoming_events", lambda **k: {"events": []})

        result = risk_mod.get_market_risk_score("NIFTY")
        # vix 0.35 + event 0.30 reliable → confidence 0.65
        assert result["confidence"] == 0.65
        assert result["is_degraded"] is True
        assert set(result["degraded_components"]) == {"pcr", "regime"}
        assert "degraded" in result["recommendation"].lower()

    def test_all_degraded_confidence_zero(self, monkeypatch):
        import src.intelligence.risk as risk_mod
        self._clear(risk_mod)
        monkeypatch.setattr(risk_mod, "_vix_component", lambda: (50, "vix down", False))
        monkeypatch.setattr(risk_mod, "_event_component", lambda: (0, "ev", False))
        monkeypatch.setattr(risk_mod, "_pcr_component", lambda s: (50, "pcr down", False))
        monkeypatch.setattr(risk_mod, "_regime_component", lambda s: (50, "rg down", False))
        monkeypatch.setattr(risk_mod, "get_upcoming_events", lambda **k: {"events": []})

        result = risk_mod.get_market_risk_score("NIFTY")
        assert result["confidence"] == 0.0
        assert result["is_degraded"] is True

    def test_legacy_two_tuple_stub_treated_reliable(self, monkeypatch):
        # _unpack tolerance: a 2-tuple component (test stub / legacy) is ok=True.
        import src.intelligence.risk as risk_mod
        self._clear(risk_mod)
        monkeypatch.setattr(risk_mod, "_vix_component", lambda: (15, "vix"))
        monkeypatch.setattr(risk_mod, "_event_component", lambda: (0, "ev"))
        monkeypatch.setattr(risk_mod, "_pcr_component", lambda s: (25, "pcr"))
        monkeypatch.setattr(risk_mod, "_regime_component", lambda s: (25, "rg"))
        monkeypatch.setattr(risk_mod, "get_upcoming_events", lambda **k: {"events": []})

        result = risk_mod.get_market_risk_score("NIFTY")
        assert result["confidence"] == 1.0
        assert result["is_degraded"] is False

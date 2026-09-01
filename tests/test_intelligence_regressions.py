"""
Intelligence regression guards — Phase 10.

These tests protect against specific failure modes discovered or anticipated
during Phase 10 development:

  IR-1: Dashboard builds when intelligence section raises
  IR-2: Trade plan builds when risk score component raises
  IR-3: _build_summary remains backward compatible without intelligence arg
  IR-4: Risk score works with empty events list
  IR-5: Risk score works when PCR is unavailable
"""
from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# IR-1: Dashboard must not break when intelligence section fails
# ---------------------------------------------------------------------------

class TestIR1DashboardIntelligenceFailure:
    """build_dashboard() must succeed even if _intelligence_section() raises."""

    def test_dashboard_returns_without_intelligence(self, monkeypatch):
        import src.dashboard.service as svc

        # Patch the four intelligence fetchers to all raise
        monkeypatch.setattr(svc, "_intelligence_section",
                            lambda sym: (_ for _ in ()).throw(RuntimeError("intel down")))

        # Also patch heavy sections to avoid live network calls
        monkeypatch.setattr(svc, "_options_section",
                            lambda sym: ({"pcr": 1.1, "pcr_interpretation": "mildly bullish",
                                          "max_pain": 22000, "distance_from_spot": 100,
                                          "supports": [], "resistances": [],
                                          "nearest_support": None, "nearest_resistance": None,
                                          "expiry": "26-Jun-2026"}, 22100.0))
        monkeypatch.setattr(svc, "_technicals_section",
                            lambda sym: ({"rsi": 55.0, "ema20": 22000.0, "ema50": 21800.0,
                                          "adx": 25.0,
                                          "macd": {"macd": 0.1, "signal": 0.05, "histogram": 0.05},
                                          "atr": 150.0}, 22100.0))
        monkeypatch.setattr(svc, "_analysis_section",
                            lambda sym: {"market_structure": {
                                "price": 22100.0, "ema20": 22000.0, "ema50": 21800.0,
                                "adx": 25.0, "rsi": 55.0,
                                "price_above_ema20": True, "ema20_above_ema50": True,
                                "adx_above_25": False, "rsi_above_60": False,
                                "descriptor": ["price_above_ema20", "ema20_above_ema50"],
                                "indicator_interpretation": {
                                    "type": "INTERPRETATION", "validation_status": "UNVALIDATED",
                                    "adx_note": "trend_weak", "rsi_note": "momentum_neutral",
                                },
                            }})

        result = svc.build_dashboard("NIFTY")

        # Dashboard must have all core keys
        assert "symbol" in result
        assert "summary" in result
        assert "options" in result
        assert "technicals" in result
        # intelligence key present but None (failure path)
        assert "intelligence" in result
        assert result["intelligence"] is None

    def test_intelligence_error_does_not_affect_summary(self, monkeypatch):
        import src.dashboard.service as svc

        monkeypatch.setattr(svc, "_intelligence_section",
                            lambda sym: (_ for _ in ()).throw(RuntimeError("intel down")))
        monkeypatch.setattr(svc, "_options_section",
                            lambda sym: ({"pcr": None, "pcr_interpretation": None,
                                          "max_pain": None, "distance_from_spot": None,
                                          "supports": [], "resistances": [],
                                          "nearest_support": None, "nearest_resistance": None,
                                          "expiry": None}, None))
        monkeypatch.setattr(svc, "_technicals_section",
                            lambda sym: ({"rsi": 50.0, "ema20": None, "ema50": None,
                                          "adx": 15.0, "macd": 0.0, "macd_signal": 0.0,
                                          "macd_histogram": 0.0, "atr": 100.0}, None))
        monkeypatch.setattr(svc, "_analysis_section",
                            lambda sym: {"market_structure": {
                                "price": None, "ema20": None, "ema50": None,
                                "adx": 15.0, "rsi": 50.0,
                                "price_above_ema20": False, "ema20_above_ema50": False,
                                "adx_above_25": False, "rsi_above_60": False,
                                "descriptor": [],
                                "indicator_interpretation": {
                                    "type": "INTERPRETATION", "validation_status": "UNVALIDATED",
                                    "adx_note": "trend_absent", "rsi_note": "momentum_neutral",
                                },
                            }})

        result = svc.build_dashboard("NIFTY")
        assert isinstance(result["summary"], str)
        assert len(result["summary"]) > 0


# ---------------------------------------------------------------------------
# IR-2: Trade plan builds when risk score component raises
# ---------------------------------------------------------------------------

class TestIR2TradePlanRiskScoreFailure:
    """create_trade_plan() must not fail if get_market_risk_score raises."""

    def test_trade_plan_succeeds_with_failed_risk_score(self, monkeypatch):
        import src.planner.trade_plan as tp

        # Patch risk score helper to raise
        monkeypatch.setattr(tp, "_risk_score_context",
                            lambda sym: (_ for _ in ()).throw(RuntimeError("risk score down")))

        # Patch underlying analysis so we don't hit network
        monkeypatch.setattr(
            "src.analysis.regime.generate_trade_setup",
            lambda sym: {
                "signal": "BUY", "confidence": 70,
                "entry": 22100.0, "stoploss": 21900.0, "target": 22500.0,
            },
        )
        monkeypatch.setattr(
            "src.analysis.regime.recommend_strategy",
            lambda sym: {
                "recommended": "Bull Call Spread", "regime": "BULL_TREND",
                "secondary": None, "reason": "trending",
            },
        )
        monkeypatch.setattr(
            "src.analysis.regime.calculate_risk_reward",
            lambda e, sl, t: {"risk": 200.0, "reward": 400.0, "rr": 2.0},
        )
        monkeypatch.setattr(
            "src.analysis.regime.calculate_position_size",
            lambda *a: {"capital": 100000, "risk_percent": 1.0,
                        "risk_amount": 1000.0, "position_size": 5},
        )
        monkeypatch.setattr(tp, "_options_context", lambda sym: {})

        # Should not raise even though _risk_score_context raises
        # The helper itself catches exceptions, so this tests the helper's own guard
        result = tp.create_trade_plan("NIFTY")
        assert "error" not in result
        assert "trade_allowed" in result

    def test_risk_score_none_when_unavailable(self, monkeypatch):
        """_risk_score_context returns None on any exception."""
        # Force the import inside _risk_score_context to fail
        import importlib

        import src.planner.trade_plan as tp
        original = __builtins__.__import__ if hasattr(__builtins__, "__import__") else None

        # Simpler: just call it with the intelligence module patched to raise
        import src.intelligence.risk as risk_mod
        with risk_mod._LOCK:
            risk_mod._CACHE.clear()

        def bad_score(sym):
            raise RuntimeError("unavailable")

        monkeypatch.setattr(risk_mod, "get_market_risk_score", bad_score)

        result = tp._risk_score_context("NIFTY")
        assert result is None


# ---------------------------------------------------------------------------
# IR-3: _build_summary backward compatible without intelligence argument
# ---------------------------------------------------------------------------

class TestIR3SummaryBackwardCompat:
    """_build_summary must work without passing intelligence (old callers)."""

    def test_no_intelligence_arg_works(self):
        from src.dashboard.service import _build_summary

        tech = {"rsi": 55.0, "ema20": 22000.0, "ema50": 21800.0, "adx": 25.0}
        opts = {"pcr": 1.1}
        analysis = {"market_structure": {"indicator_interpretation": {}}}

        # Call without intelligence — should not raise
        result = _build_summary("NIFTY", 22100.0, tech, opts, analysis)
        assert isinstance(result, str)
        assert "NIFTY" in result

    def test_intelligence_none_produces_same_format(self):
        from src.dashboard.service import _build_summary

        tech = {"rsi": 55.0, "ema20": 22000.0, "ema50": 21800.0, "adx": 25.0}
        opts = {"pcr": 1.1}
        analysis = {"market_structure": {"indicator_interpretation": {}}}

        r1 = _build_summary("NIFTY", 22100.0, tech, opts, analysis)
        r2 = _build_summary("NIFTY", 22100.0, tech, opts, analysis, intelligence=None)
        assert r1 == r2

    def test_summary_contains_event_warning_when_present(self):
        from src.dashboard.service import _build_summary

        tech = {"rsi": 55.0, "ema20": 22000.0, "ema50": 21800.0, "adx": 25.0}
        opts = {"pcr": 1.1}
        analysis = {"market_structure": {"indicator_interpretation": {}}}
        intelligence = {
            "upcoming_events": [{
                "days_until": 1,
                "impact": "HIGH",
                "description": "RBI MPC Decision",
                "date": "2026-06-18",
                "event_type": "RBI_MPC",
            }]
        }

        result = _build_summary("NIFTY", 22100.0, tech, opts, analysis,
                                intelligence=intelligence)
        assert "RBI MPC Decision" in result

    def test_no_warning_when_event_beyond_3_days(self):
        from src.dashboard.service import _build_summary

        tech = {"rsi": 55.0, "ema20": 22000.0, "ema50": 21800.0, "adx": 25.0}
        opts = {"pcr": 1.1}
        analysis = {"market_structure": {"indicator_interpretation": {}}}
        intelligence = {
            "upcoming_events": [{
                "days_until": 5,
                "impact": "HIGH",
                "description": "RBI MPC Decision",
                "date": "2026-06-22",
                "event_type": "RBI_MPC",
            }]
        }

        result = _build_summary("NIFTY", 22100.0, tech, opts, analysis,
                                intelligence=intelligence)
        # No event warning expected since 5 > 3
        assert "RBI MPC Decision" not in result


# ---------------------------------------------------------------------------
# IR-4: Risk score works with empty events list
# ---------------------------------------------------------------------------

class TestIR4RiskScoreEmptyEvents:
    def test_empty_events_does_not_raise(self, monkeypatch):
        import src.intelligence.risk as risk_mod

        with risk_mod._LOCK:
            risk_mod._CACHE.clear()

        monkeypatch.setattr(risk_mod, "_vix_component", lambda: (45, "VIX moderate"))
        monkeypatch.setattr(risk_mod, "_event_component", lambda: (0, "No events"))
        monkeypatch.setattr(risk_mod, "_pcr_component", lambda sym: (25, "PCR ok"))
        monkeypatch.setattr(risk_mod, "_regime_component", lambda sym: (25, "Regime ok"))
        monkeypatch.setattr(
            risk_mod, "get_upcoming_events",
            lambda **kw: {"events": [], "nearest_high_impact_days": None},
        )

        result = risk_mod.get_market_risk_score("NIFTY")
        assert "error" not in result
        assert "score" in result
        assert 0 <= result["score"] <= 100

    def test_event_score_zero_when_no_high_impact(self):
        from src.intelligence.risk import _event_score
        assert _event_score({"events": []}) == 0

    def test_nearest_high_impact_days_none_with_empty_events(self):
        from src.intelligence.events import nearest_high_impact_days
        assert nearest_high_impact_days([]) is None


# ---------------------------------------------------------------------------
# IR-5: Risk score works when PCR is unavailable
# ---------------------------------------------------------------------------

class TestIR5RiskScorePcrUnavailable:
    def test_pcr_exception_returns_neutral_50(self, monkeypatch):
        """_pcr_component must return (50, ...) when options service raises."""
        import src.intelligence.risk as risk_mod

        # Patch options service to raise
        monkeypatch.setattr(
            "src.options.service.get_options_service",
            lambda: (_ for _ in ()).throw(RuntimeError("options unavailable")),
        )

        score, desc, ok = risk_mod._pcr_component("NIFTY")
        assert score == 50
        assert ok is False, "a fallback PCR component must report ok=False"
        assert "unavailable" in desc.lower() or "neutral" in desc.lower()

    def test_full_score_still_valid_without_pcr(self, monkeypatch):
        import src.intelligence.risk as risk_mod

        with risk_mod._LOCK:
            risk_mod._CACHE.clear()

        monkeypatch.setattr(risk_mod, "_vix_component", lambda: (45, "VIX ok"))
        monkeypatch.setattr(risk_mod, "_event_component", lambda: (20, "events ok"))
        # PCR falls back to neutral
        monkeypatch.setattr(
            risk_mod, "_pcr_component",
            lambda sym: (50, "PCR unavailable — using neutral 50"),
        )
        monkeypatch.setattr(risk_mod, "_regime_component", lambda sym: (25, "regime ok"))
        monkeypatch.setattr(
            risk_mod, "get_upcoming_events",
            lambda **kw: {"events": [], "nearest_high_impact_days": None},
        )

        result = risk_mod.get_market_risk_score("NIFTY")
        assert "error" not in result
        assert result["score"] == round(45 * 0.35 + 20 * 0.30 + 50 * 0.20 + 25 * 0.15)

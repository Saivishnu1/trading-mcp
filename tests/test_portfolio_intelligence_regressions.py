"""
Portfolio Intelligence regression guards — Phase 11A.

  PR-1: Empty holdings + empty positions → valid structured response, no exception
  PR-2: Broker call fails (no session) → {"error": ...}, not unhandled exception
  PR-3: Per-symbol analysis failure → other positions still included in report
  PR-4: All per-symbol analysis fails → exposure breakdown keys still present
  PR-5: Same symbol in holdings AND positions → analyzed/returned once
"""
from __future__ import annotations

import pytest


def _holding(sym, qty=100, avg=1000.0, last=1050.0, pnl=5000.0):
    return {
        "tradingsymbol": sym, "exchange": "NSE",
        "quantity": qty, "average_price": avg,
        "last_price": last, "pnl": pnl,
    }


def _position(sym, qty=50, avg=500.0, last=520.0, pnl=1000.0):
    return {
        "tradingsymbol": sym, "exchange": "NSE",
        "quantity": qty, "average_price": avg,
        "last_price": last, "pnl": pnl, "product": "MIS",
    }


class _ErrorBroker:
    def holdings(self):
        raise RuntimeError("no active session — call zerodha_login first")
    def positions(self):
        raise RuntimeError("no active session — call zerodha_login first")


def _fake_broker(holdings=None, positions=None):
    class FakeBroker:
        def holdings(self): return holdings or []
        def positions(self): return {"net": positions or [], "day": []}
    return FakeBroker()


# ---------------------------------------------------------------------------
# PR-1: Empty portfolio returns valid structured response
# ---------------------------------------------------------------------------

class TestPR1EmptyPortfolio:
    def test_risk_report_empty_portfolio(self, monkeypatch):
        import src.broker as broker_mod
        monkeypatch.setattr(broker_mod, "get_broker", lambda: _fake_broker())

        from src.portfolio_intelligence.service import get_portfolio_risk_report
        result = get_portfolio_risk_report()

        assert "error" not in result
        assert result["total_positions"] == 0
        assert isinstance(result["per_position_analysis"], list)
        assert isinstance(result["recommendations"], list)
        assert "portfolio_risk_score" in result
        assert "diversification_score" in result
        assert "concentration_risk" in result

    def test_regime_analysis_empty_portfolio(self, monkeypatch):
        import src.broker as broker_mod
        monkeypatch.setattr(broker_mod, "get_broker", lambda: _fake_broker())

        from src.portfolio_intelligence.service import get_portfolio_regime_analysis
        result = get_portfolio_regime_analysis()

        assert "error" not in result
        assert result["total_positions"] == 0
        assert result["regime_counts"] == {}
        assert isinstance(result["summary"], str)

    def test_exposure_breakdown_empty_portfolio(self, monkeypatch):
        import src.broker as broker_mod
        monkeypatch.setattr(broker_mod, "get_broker", lambda: _fake_broker())

        from src.portfolio_intelligence.service import get_portfolio_exposure_breakdown
        result = get_portfolio_exposure_breakdown()

        assert "error" not in result
        assert result["total_positions"] == 0
        assert result["long_exposure"] == 0.0
        assert result["largest_position"] is None


# ---------------------------------------------------------------------------
# PR-2: Broker raises (no session) → error dict, not exception
# ---------------------------------------------------------------------------

class TestPR2BrokerAuthFailure:
    def test_risk_report_no_session(self, monkeypatch):
        import src.broker as broker_mod
        monkeypatch.setattr(broker_mod, "get_broker", lambda: _ErrorBroker())

        from src.portfolio_intelligence.service import get_portfolio_risk_report
        result = get_portfolio_risk_report()
        assert "error" in result
        assert "error" in result["error"].lower() or "session" in result["error"].lower()

    def test_regime_analysis_no_session(self, monkeypatch):
        import src.broker as broker_mod
        monkeypatch.setattr(broker_mod, "get_broker", lambda: _ErrorBroker())

        from src.portfolio_intelligence.service import get_portfolio_regime_analysis
        result = get_portfolio_regime_analysis()
        assert "error" in result

    def test_exposure_breakdown_no_session(self, monkeypatch):
        import src.broker as broker_mod
        monkeypatch.setattr(broker_mod, "get_broker", lambda: _ErrorBroker())

        from src.portfolio_intelligence.service import get_portfolio_exposure_breakdown
        result = get_portfolio_exposure_breakdown()
        assert "error" in result

    def test_no_exception_propagates(self, monkeypatch):
        import src.broker as broker_mod
        monkeypatch.setattr(broker_mod, "get_broker", lambda: _ErrorBroker())

        from src.portfolio_intelligence.service import (
            get_portfolio_exposure_breakdown,
            get_portfolio_regime_analysis,
            get_portfolio_risk_report,
        )
        # None of these should raise
        get_portfolio_risk_report()
        get_portfolio_regime_analysis()
        get_portfolio_exposure_breakdown()


# ---------------------------------------------------------------------------
# PR-3: One symbol's analysis fails → other positions still in report
# ---------------------------------------------------------------------------

class TestPR3PerSymbolAnalysisFailure:
    def test_failed_symbol_included_with_nulls(self, monkeypatch):
        import src.broker as broker_mod
        import src.portfolio_intelligence.service as svc

        monkeypatch.setattr(broker_mod, "get_broker", lambda: _fake_broker(
            holdings=[_holding("INFY"), _holding("TCS")],
        ))

        call_count = [0]
        def selective_fail(pos):
            call_count[0] += 1
            if pos["symbol"] == "INFY":
                raise RuntimeError("data unavailable for INFY")
            return {
                **pos,
                "risk_score": 45, "risk_rating": "MODERATE",
                "regime": "BULL_TREND", "review_action": "HOLD",
                "thesis_status": "VALID", "current_signal": "BUY",
                "confidence": 70,
            }

        # _analyze_position already isolates exceptions — patch the inner functions
        # to simulate failure by patching review_trade and get_market_risk_score
        from src.intelligence import risk as risk_mod
        from src.review import reviewer

        call_tracker = {"infy": 0, "tcs": 0}

        def fake_review(sym, direction, entry_price=None, holding_days=None):
            if sym == "INFY":
                raise RuntimeError("review failed for INFY")
            return {
                "symbol": sym, "action": "HOLD", "thesis_status": "VALID",
                "current_regime": "BULL_TREND", "current_signal": "BUY",
                "confidence": 70, "direction": direction,
                "current_price": 3500.0,
            }

        def fake_risk(sym):
            return {"score": 45, "rating": "MODERATE"}

        monkeypatch.setattr(reviewer, "review_trade", fake_review)
        monkeypatch.setattr(risk_mod, "get_market_risk_score", fake_risk)

        from src.portfolio_intelligence.service import get_portfolio_risk_report
        result = get_portfolio_risk_report()

        # Both positions must appear
        assert result["total_positions"] == 2
        syms = {a["symbol"] for a in result["per_position_analysis"]}
        assert "INFY" in syms
        assert "TCS" in syms

        # TCS should have review data; INFY should have nulls / error key
        tcs_analysis = next(a for a in result["per_position_analysis"] if a["symbol"] == "TCS")
        assert tcs_analysis["review_action"] == "HOLD"

        infy_analysis = next(a for a in result["per_position_analysis"] if a["symbol"] == "INFY")
        assert infy_analysis["review_action"] is None


# ---------------------------------------------------------------------------
# PR-4: All per-symbol analysis fails → exposure keys still valid
# ---------------------------------------------------------------------------

class TestPR4AllAnalysisFailed:
    def test_exposure_keys_present_when_all_analysis_fails(self, monkeypatch):
        import src.broker as broker_mod
        from src.intelligence import risk as risk_mod
        from src.review import reviewer

        monkeypatch.setattr(broker_mod, "get_broker", lambda: _fake_broker(
            holdings=[_holding("INFY"), _holding("TCS")],
        ))
        monkeypatch.setattr(reviewer, "review_trade",
                            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("all down")))
        monkeypatch.setattr(risk_mod, "get_market_risk_score",
                            lambda sym: (_ for _ in ()).throw(RuntimeError("all down")))

        from src.portfolio_intelligence.service import get_portfolio_risk_report
        result = get_portfolio_risk_report()

        # Core exposure keys must always be present
        assert result["total_positions"] == 2
        assert "per_position_analysis" in result
        assert "concentration_risk" in result
        assert "diversification_score" in result

    def test_portfolio_score_falls_back_to_neutral(self, monkeypatch):
        import src.broker as broker_mod
        from src.intelligence import risk as risk_mod
        from src.review import reviewer

        monkeypatch.setattr(broker_mod, "get_broker", lambda: _fake_broker(
            holdings=[_holding("INFY")],
        ))
        monkeypatch.setattr(reviewer, "review_trade",
                            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("down")))
        monkeypatch.setattr(risk_mod, "get_market_risk_score",
                            lambda sym: (_ for _ in ()).throw(RuntimeError("down")))

        from src.portfolio_intelligence.service import get_portfolio_risk_report
        result = get_portfolio_risk_report()

        # Falls back to neutral 50 when no risk scores available
        assert result["portfolio_risk_score"] == 50
        assert result["rating"] == "MODERATE"


# ---------------------------------------------------------------------------
# PR-5: Same symbol in holdings AND positions → returned once, not twice
# ---------------------------------------------------------------------------

class TestPR5SymbolDeduplication:
    def test_deduplication_in_risk_report(self, monkeypatch):
        import src.broker as broker_mod
        import src.portfolio_intelligence.service as svc
        from src.intelligence import risk as risk_mod
        from src.review import reviewer

        # RELIANCE in both holdings AND net positions
        monkeypatch.setattr(broker_mod, "get_broker", lambda: _fake_broker(
            holdings=[_holding("RELIANCE", qty=50, last=2900.0)],
            positions=[_position("RELIANCE", qty=10, last=2900.0)],
        ))
        monkeypatch.setattr(reviewer, "review_trade",
                            lambda sym, direction, entry_price=None, **kw: {
                                "symbol": sym, "action": "HOLD",
                                "thesis_status": "VALID",
                                "current_regime": "BULL_TREND",
                                "current_signal": "BUY", "confidence": 70,
                                "direction": direction, "current_price": 2900.0,
                            })
        monkeypatch.setattr(risk_mod, "get_market_risk_score",
                            lambda sym: {"score": 40, "rating": "MODERATE"})

        from src.portfolio_intelligence.service import get_portfolio_risk_report
        result = get_portfolio_risk_report()

        # RELIANCE must appear exactly once
        reliance_entries = [
            a for a in result["per_position_analysis"] if a["symbol"] == "RELIANCE"
        ]
        assert len(reliance_entries) == 1

    def test_deduplication_in_exposure_breakdown(self, monkeypatch):
        import src.broker as broker_mod

        monkeypatch.setattr(broker_mod, "get_broker", lambda: _fake_broker(
            holdings=[_holding("TCS", qty=10, last=3500.0)],
            positions=[_position("TCS", qty=5, last=3500.0)],
        ))

        from src.portfolio_intelligence.service import get_portfolio_exposure_breakdown
        result = get_portfolio_exposure_breakdown()

        # TCS should appear exactly once in top_exposures
        tcs_entries = [e for e in result["top_exposures"] if e["symbol"] == "TCS"]
        assert len(tcs_entries) == 1

    def test_holding_data_used_not_position(self, monkeypatch):
        import src.broker as broker_mod

        # Holding has qty=50, position has qty=5 for same symbol
        monkeypatch.setattr(broker_mod, "get_broker", lambda: _fake_broker(
            holdings=[_holding("INFY", qty=50, last=1600.0)],
            positions=[_position("INFY", qty=5, last=1600.0)],
        ))

        from src.portfolio_intelligence.service import _get_all_positions
        result = _get_all_positions()

        infy = next(p for p in result if p["symbol"] == "INFY")
        # Must come from holding (qty=50), not position (qty=5)
        assert infy["quantity"] == 50
        assert infy["source"] == "holding"

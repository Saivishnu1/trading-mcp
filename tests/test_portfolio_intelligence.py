"""Tests for src/portfolio_intelligence/service.py"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _holding(sym, qty=100, avg=1000.0, last=1050.0, pnl=5000.0, exchange="NSE"):
    return {
        "tradingsymbol": sym,
        "exchange": exchange,
        "quantity": qty,
        "average_price": avg,
        "last_price": last,
        "pnl": pnl,
    }


def _position(sym, qty=50, avg=500.0, last=520.0, pnl=1000.0, product="MIS", exchange="NSE"):
    return {
        "tradingsymbol": sym,
        "exchange": exchange,
        "quantity": qty,
        "average_price": avg,
        "last_price": last,
        "pnl": pnl,
        "product": product,
    }


def _fake_broker(holdings=None, positions=None):
    class FakeBroker:
        def holdings(self):
            return holdings or []
        def positions(self):
            return {"net": positions or [], "day": []}
    return FakeBroker()


def _patch_broker(monkeypatch, holdings=None, positions=None):
    import src.portfolio_intelligence.service as svc
    broker = _fake_broker(holdings, positions)
    monkeypatch.setattr(svc, "_get_all_positions",
                        lambda: svc._get_all_positions.__wrapped__(broker, holdings, positions)
                        if hasattr(svc._get_all_positions, "__wrapped__") else None)
    # Simpler: patch get_broker directly
    import src.broker as broker_mod
    monkeypatch.setattr(broker_mod, "get_broker", lambda: broker)


# ---------------------------------------------------------------------------
# Diversification score
# ---------------------------------------------------------------------------

class TestDiversificationScore:
    def test_empty_returns_zero(self):
        from src.portfolio_intelligence.service import _diversification_score
        assert _diversification_score([]) == 0

    def test_single_position_returns_zero(self):
        from src.portfolio_intelligence.service import _diversification_score
        positions = [{"current_value": 10000}]
        assert _diversification_score(positions) == 0

    def test_two_equal_positions_returns_50(self):
        from src.portfolio_intelligence.service import _diversification_score
        positions = [{"current_value": 5000}, {"current_value": 5000}]
        assert _diversification_score(positions) == 50

    def test_three_equal_positions(self):
        from src.portfolio_intelligence.service import _diversification_score
        positions = [{"current_value": 3333} for _ in range(3)]
        result = _diversification_score(positions)
        # 1 - 3*(1/3)^2 = 1 - 1/3 = 0.667 → 67
        assert 60 <= result <= 70

    def test_ten_equal_positions(self):
        from src.portfolio_intelligence.service import _diversification_score
        positions = [{"current_value": 1000} for _ in range(10)]
        result = _diversification_score(positions)
        # 1 - 10*(0.1)^2 = 0.9 → 90
        assert result == 90

    def test_highly_concentrated_low_score(self):
        from src.portfolio_intelligence.service import _diversification_score
        # 95% in one position
        positions = [{"current_value": 9500}, {"current_value": 500}]
        result = _diversification_score(positions)
        assert result < 20

    def test_zero_values_ignored(self):
        from src.portfolio_intelligence.service import _diversification_score
        positions = [{"current_value": 0}, {"current_value": 0}]
        assert _diversification_score(positions) == 0


# ---------------------------------------------------------------------------
# Concentration risk
# ---------------------------------------------------------------------------

class TestConcentrationRisk:
    def test_empty_returns_not_concentrated(self):
        from src.portfolio_intelligence.service import _concentration_risk
        result = _concentration_risk([])
        assert result["concentrated"] is False
        assert result["max_single_position_pct"] == 0

    def test_single_position_100pct(self):
        from src.portfolio_intelligence.service import _concentration_risk
        positions = [{"symbol": "INFY", "current_value": 10000}]
        result = _concentration_risk(positions)
        assert result["max_single_position_pct"] == 100.0
        assert result["concentrated"] is True
        assert result["concentrated_symbol"] == "INFY"

    def test_below_30_pct_not_concentrated(self):
        from src.portfolio_intelligence.service import _concentration_risk
        # 25% in one, 75% spread across others
        positions = [
            {"symbol": "A", "current_value": 2500},
            {"symbol": "B", "current_value": 2500},
            {"symbol": "C", "current_value": 2500},
            {"symbol": "D", "current_value": 2500},
        ]
        result = _concentration_risk(positions)
        assert result["concentrated"] is False
        assert result["concentrated_symbol"] is None

    def test_above_30_pct_concentrated(self):
        from src.portfolio_intelligence.service import _concentration_risk
        positions = [
            {"symbol": "REL", "current_value": 4000},
            {"symbol": "TCS", "current_value": 3000},
            {"symbol": "INF", "current_value": 3000},
        ]
        result = _concentration_risk(positions)
        assert result["concentrated"] is True
        assert result["concentrated_symbol"] == "REL"
        assert result["max_single_position_pct"] == 40.0


# ---------------------------------------------------------------------------
# Portfolio risk score
# ---------------------------------------------------------------------------

class TestPortfolioRiskScore:
    def test_empty_returns_neutral_50(self):
        from src.portfolio_intelligence.service import _portfolio_risk_score
        score, rating = _portfolio_risk_score([])
        assert score == 50
        assert rating == "MODERATE"

    def test_single_position(self):
        from src.portfolio_intelligence.service import _portfolio_risk_score
        analyses = [{"risk_score": 70, "current_value": 10000}]
        score, rating = _portfolio_risk_score(analyses)
        assert score == 70
        assert rating == "HIGH"

    def test_weighted_by_value(self):
        from src.portfolio_intelligence.service import _portfolio_risk_score
        # 80% weight on score=20 (value=8000), 20% weight on score=80 (value=2000)
        # expected = 0.8*20 + 0.2*80 = 16 + 16 = 32
        analyses = [
            {"risk_score": 20, "current_value": 8000},
            {"risk_score": 80, "current_value": 2000},
        ]
        score, _ = _portfolio_risk_score(analyses)
        assert score == 32

    def test_none_risk_scores_excluded(self):
        from src.portfolio_intelligence.service import _portfolio_risk_score
        analyses = [
            {"risk_score": None, "current_value": 5000},
            {"risk_score": 60, "current_value": 5000},
        ]
        score, _ = _portfolio_risk_score(analyses)
        assert score == 60

    def test_all_none_returns_neutral(self):
        from src.portfolio_intelligence.service import _portfolio_risk_score
        analyses = [{"risk_score": None, "current_value": 5000}]
        score, rating = _portfolio_risk_score(analyses)
        assert score == 50
        assert rating == "MODERATE"

    def test_clamped_to_100(self):
        from src.portfolio_intelligence.service import _portfolio_risk_score
        analyses = [{"risk_score": 100, "current_value": 1000}]
        score, _ = _portfolio_risk_score(analyses)
        assert score == 100

    def test_rating_thresholds(self):
        from src.portfolio_intelligence.service import _risk_rating
        assert _risk_rating(0)   == "LOW"
        assert _risk_rating(29)  == "LOW"
        assert _risk_rating(30)  == "MODERATE"
        assert _risk_rating(59)  == "MODERATE"
        assert _risk_rating(60)  == "HIGH"
        assert _risk_rating(79)  == "HIGH"
        assert _risk_rating(80)  == "EXTREME"
        assert _risk_rating(100) == "EXTREME"


# ---------------------------------------------------------------------------
# Top risks
# ---------------------------------------------------------------------------

class TestTopRisks:
    def _make(self, sym, score):
        return {"symbol": sym, "risk_score": score, "risk_rating": "HIGH", "review_action": "HOLD"}

    def test_empty_returns_empty(self):
        from src.portfolio_intelligence.service import _top_risks
        assert _top_risks([]) == []

    def test_none_risk_scores_excluded(self):
        from src.portfolio_intelligence.service import _top_risks
        analyses = [{"symbol": "A", "risk_score": None, "risk_rating": None, "review_action": None}]
        assert _top_risks(analyses) == []

    def test_returns_max_3(self):
        from src.portfolio_intelligence.service import _top_risks
        analyses = [self._make(f"S{i}", i * 10) for i in range(6)]
        result = _top_risks(analyses)
        assert len(result) == 3

    def test_sorted_descending(self):
        from src.portfolio_intelligence.service import _top_risks
        analyses = [self._make("A", 30), self._make("B", 70), self._make("C", 50)]
        result = _top_risks(analyses)
        scores = [r["risk_score"] for r in result]
        assert scores == sorted(scores, reverse=True)

    def test_fewer_than_3_returns_all(self):
        from src.portfolio_intelligence.service import _top_risks
        analyses = [self._make("A", 40), self._make("B", 60)]
        assert len(_top_risks(analyses)) == 2


# ---------------------------------------------------------------------------
# Recommendations
# ---------------------------------------------------------------------------

class TestRecommendations:
    def _conc(self, pct, sym=None):
        return {
            "max_single_position_pct": pct,
            "concentrated": pct > 30,
            "concentrated_symbol": sym if pct > 30 else None,
        }

    def test_exit_signal_included(self):
        from src.portfolio_intelligence.service import _recommendations
        analyses = [{"symbol": "INFY", "review_action": "EXIT"}]
        recs = _recommendations(45, analyses, self._conc(20))
        assert any("INFY" in r and "exit" in r.lower() for r in recs)

    def test_reduce_signal_included(self):
        from src.portfolio_intelligence.service import _recommendations
        analyses = [{"symbol": "TCS", "review_action": "REDUCE"}]
        recs = _recommendations(45, analyses, self._conc(20))
        assert any("TCS" in r and "reduc" in r.lower() for r in recs)

    def test_concentration_flag_included(self):
        from src.portfolio_intelligence.service import _recommendations
        analyses = []
        recs = _recommendations(45, analyses, self._conc(40, "RELIANCE"))
        assert any("RELIANCE" in r for r in recs)

    def test_extreme_risk_recommendation(self):
        from src.portfolio_intelligence.service import _recommendations
        recs = _recommendations(85, [], self._conc(20))
        assert any("EXTREME" in r for r in recs)

    def test_high_risk_recommendation(self):
        from src.portfolio_intelligence.service import _recommendations
        recs = _recommendations(65, [], self._conc(20))
        assert any("HIGH" in r for r in recs)

    def test_low_risk_recommendation(self):
        from src.portfolio_intelligence.service import _recommendations
        recs = _recommendations(20, [], self._conc(20))
        assert any("LOW" in r or "favorable" in r for r in recs)

    def test_default_no_action_message(self):
        from src.portfolio_intelligence.service import _recommendations
        recs = _recommendations(45, [{"symbol": "A", "review_action": "HOLD"}], self._conc(20))
        assert any("No immediate" in r for r in recs)


# ---------------------------------------------------------------------------
# _get_all_positions
# ---------------------------------------------------------------------------

class TestGetAllPositions:
    def test_holdings_only(self, monkeypatch):
        import src.broker as broker_mod
        monkeypatch.setattr(broker_mod, "get_broker", lambda: _fake_broker(
            holdings=[_holding("INFY", qty=100, avg=1500.0, last=1600.0)],
        ))
        from src.portfolio_intelligence.service import _get_all_positions
        result = _get_all_positions()
        assert len(result) == 1
        assert result[0]["symbol"] == "INFY"
        assert result[0]["direction"] == "LONG"
        assert result[0]["quantity"] == 100
        assert result[0]["current_value"] == 100 * 1600.0

    def test_positions_only(self, monkeypatch):
        import src.broker as broker_mod
        monkeypatch.setattr(broker_mod, "get_broker", lambda: _fake_broker(
            positions=[_position("RELIANCE", qty=50, last=2800.0)],
        ))
        from src.portfolio_intelligence.service import _get_all_positions
        result = _get_all_positions()
        assert len(result) == 1
        assert result[0]["symbol"] == "RELIANCE"
        assert result[0]["direction"] == "LONG"

    def test_short_position(self, monkeypatch):
        import src.broker as broker_mod
        monkeypatch.setattr(broker_mod, "get_broker", lambda: _fake_broker(
            positions=[_position("NIFTY", qty=-2, last=22000.0)],
        ))
        from src.portfolio_intelligence.service import _get_all_positions
        result = _get_all_positions()
        assert result[0]["direction"] == "SHORT"
        assert result[0]["quantity"] == 2

    def test_deduplication_holding_wins(self, monkeypatch):
        import src.broker as broker_mod
        monkeypatch.setattr(broker_mod, "get_broker", lambda: _fake_broker(
            holdings=[_holding("TCS", qty=10, last=3500.0)],
            positions=[_position("TCS", qty=5, last=3500.0)],
        ))
        from src.portfolio_intelligence.service import _get_all_positions
        result = _get_all_positions()
        # TCS should appear once (from holdings), not twice
        symbols = [p["symbol"] for p in result]
        assert symbols.count("TCS") == 1
        assert result[0]["source"] == "holding"

    def test_zero_quantity_holdings_skipped(self, monkeypatch):
        import src.broker as broker_mod
        monkeypatch.setattr(broker_mod, "get_broker", lambda: _fake_broker(
            holdings=[_holding("INFY", qty=0)],
        ))
        from src.portfolio_intelligence.service import _get_all_positions
        assert _get_all_positions() == []

    def test_zero_quantity_positions_skipped(self, monkeypatch):
        import src.broker as broker_mod
        monkeypatch.setattr(broker_mod, "get_broker", lambda: _fake_broker(
            positions=[_position("RELIANCE", qty=0)],
        ))
        from src.portfolio_intelligence.service import _get_all_positions
        assert _get_all_positions() == []

    def test_combined_holdings_and_unique_positions(self, monkeypatch):
        import src.broker as broker_mod
        monkeypatch.setattr(broker_mod, "get_broker", lambda: _fake_broker(
            holdings=[_holding("INFY")],
            positions=[_position("HDFCBANK", qty=20, last=1800.0)],
        ))
        from src.portfolio_intelligence.service import _get_all_positions
        result = _get_all_positions()
        assert len(result) == 2
        symbols = {p["symbol"] for p in result}
        assert symbols == {"INFY", "HDFCBANK"}


# ---------------------------------------------------------------------------
# get_portfolio_risk_report
# ---------------------------------------------------------------------------

class TestGetPortfolioRiskReport:
    def _patch_analysis(self, monkeypatch, risk_score=45, action="HOLD", regime="BULL_TREND"):
        import src.portfolio_intelligence.service as svc
        monkeypatch.setattr(svc, "_analyze_position", lambda pos: {
            "symbol":         pos["symbol"],
            "direction":      pos["direction"],
            "quantity":       pos["quantity"],
            "current_value":  pos["current_value"],
            "pnl":            pos.get("pnl"),
            "risk_score":     risk_score,
            "risk_rating":    "MODERATE",
            "regime":         regime,
            "review_action":  action,
            "thesis_status":  "VALID",
            "current_signal": "BUY",
            "confidence":     70,
        })

    def test_empty_portfolio(self, monkeypatch):
        import src.broker as broker_mod
        monkeypatch.setattr(broker_mod, "get_broker", lambda: _fake_broker())
        from src.portfolio_intelligence.service import get_portfolio_risk_report
        result = get_portfolio_risk_report()
        assert result["total_positions"] == 0
        assert result["per_position_analysis"] == []
        assert result["recommendations"] == ["No positions found."]

    def test_single_holding_returns_expected_keys(self, monkeypatch):
        import src.broker as broker_mod
        monkeypatch.setattr(broker_mod, "get_broker", lambda: _fake_broker(
            holdings=[_holding("INFY", qty=100, last=1600.0)],
        ))
        self._patch_analysis(monkeypatch)
        from src.portfolio_intelligence.service import get_portfolio_risk_report
        result = get_portfolio_risk_report()
        for key in ("total_positions", "portfolio_risk_score", "rating",
                    "diversification_score", "concentration_risk",
                    "top_risks", "recommendations", "per_position_analysis"):
            assert key in result, f"missing key: {key}"

    def test_multiple_holdings_correct_count(self, monkeypatch):
        import src.broker as broker_mod
        monkeypatch.setattr(broker_mod, "get_broker", lambda: _fake_broker(
            holdings=[_holding("INFY"), _holding("TCS"), _holding("RELIANCE")],
        ))
        self._patch_analysis(monkeypatch)
        from src.portfolio_intelligence.service import get_portfolio_risk_report
        result = get_portfolio_risk_report()
        assert result["total_positions"] == 3
        assert len(result["per_position_analysis"]) == 3

    def test_concentrated_portfolio_flagged(self, monkeypatch):
        import src.broker as broker_mod
        # One very large holding, one small
        monkeypatch.setattr(broker_mod, "get_broker", lambda: _fake_broker(
            holdings=[
                _holding("RELIANCE", qty=100, last=3000.0),  # 300000
                _holding("INFY",     qty=1,   last=100.0),   # 100
            ],
        ))
        self._patch_analysis(monkeypatch)
        from src.portfolio_intelligence.service import get_portfolio_risk_report
        result = get_portfolio_risk_report()
        assert result["concentration_risk"]["concentrated"] is True
        assert result["concentration_risk"]["concentrated_symbol"] == "RELIANCE"

    def test_broker_error_returns_error_dict(self, monkeypatch):
        import src.broker as broker_mod
        class ErrorBroker:
            def holdings(self): raise RuntimeError("no active session")
            def positions(self): raise RuntimeError("no active session")
        monkeypatch.setattr(broker_mod, "get_broker", lambda: ErrorBroker())
        from src.portfolio_intelligence.service import get_portfolio_risk_report
        result = get_portfolio_risk_report()
        assert "error" in result


# ---------------------------------------------------------------------------
# get_portfolio_regime_analysis
# ---------------------------------------------------------------------------

class TestGetPortfolioRegimeAnalysis:
    def test_empty_portfolio(self, monkeypatch):
        import src.broker as broker_mod
        monkeypatch.setattr(broker_mod, "get_broker", lambda: _fake_broker())
        from src.portfolio_intelligence.service import get_portfolio_regime_analysis
        result = get_portfolio_regime_analysis()
        assert result["total_positions"] == 0
        assert result["regime_counts"] == {}
        assert result["portfolio_directional_bias"] == "NEUTRAL"

    def test_all_bull_trend_is_bullish(self, monkeypatch):
        import src.broker as broker_mod
        import src.portfolio_intelligence.service as svc
        monkeypatch.setattr(broker_mod, "get_broker", lambda: _fake_broker(
            holdings=[_holding("A"), _holding("B")],
        ))
        monkeypatch.setattr(svc, "_analyze_position", lambda pos: {
            **pos, "regime": "BULL_TREND", "current_signal": "BUY",
            "review_action": "HOLD", "risk_score": 30, "risk_rating": "LOW",
            "thesis_status": "VALID", "confidence": 70,
        })
        from src.portfolio_intelligence.service import get_portfolio_regime_analysis
        result = get_portfolio_regime_analysis()
        assert result["portfolio_directional_bias"] == "BULLISH"
        assert result["regime_counts"]["BULL_TREND"] == 2

    def test_mixed_regimes_returns_mixed_bias(self, monkeypatch):
        import src.broker as broker_mod
        import src.portfolio_intelligence.service as svc
        holdings = [_holding("A"), _holding("B"), _holding("C"), _holding("D")]
        monkeypatch.setattr(broker_mod, "get_broker", lambda: _fake_broker(holdings=holdings))
        regimes = ["BULL_TREND", "BEAR_TREND", "BULL_TREND", "BEAR_TREND"]
        call_count = [0]
        def fake_analyze(pos):
            r = regimes[call_count[0] % len(regimes)]
            call_count[0] += 1
            return {**pos, "regime": r, "current_signal": "NEUTRAL",
                    "review_action": "HOLD", "risk_score": 45, "risk_rating": "MODERATE",
                    "thesis_status": "VALID", "confidence": 50}
        monkeypatch.setattr(svc, "_analyze_position", fake_analyze)
        from src.portfolio_intelligence.service import get_portfolio_regime_analysis
        result = get_portfolio_regime_analysis()
        assert result["portfolio_directional_bias"] == "MIXED"

    def test_summary_string_present(self, monkeypatch):
        import src.broker as broker_mod
        import src.portfolio_intelligence.service as svc
        monkeypatch.setattr(broker_mod, "get_broker", lambda: _fake_broker(
            holdings=[_holding("INFY")],
        ))
        monkeypatch.setattr(svc, "_analyze_position", lambda pos: {
            **pos, "regime": "RANGE_BOUND", "current_signal": "NEUTRAL",
            "review_action": "HOLD", "risk_score": 40, "risk_rating": "MODERATE",
            "thesis_status": "VALID", "confidence": 60,
        })
        from src.portfolio_intelligence.service import get_portfolio_regime_analysis
        result = get_portfolio_regime_analysis()
        assert isinstance(result["summary"], str)
        assert len(result["summary"]) > 0


# ---------------------------------------------------------------------------
# get_portfolio_exposure_breakdown
# ---------------------------------------------------------------------------

class TestGetPortfolioExposureBreakdown:
    def test_empty_portfolio(self, monkeypatch):
        import src.broker as broker_mod
        monkeypatch.setattr(broker_mod, "get_broker", lambda: _fake_broker())
        from src.portfolio_intelligence.service import get_portfolio_exposure_breakdown
        result = get_portfolio_exposure_breakdown()
        assert result["total_positions"] == 0
        assert result["long_exposure"] == 0.0
        assert result["short_exposure"] == 0.0
        assert result["largest_position"] is None

    def test_long_only_portfolio(self, monkeypatch):
        import src.broker as broker_mod
        monkeypatch.setattr(broker_mod, "get_broker", lambda: _fake_broker(
            holdings=[_holding("INFY", qty=10, last=1500.0),
                      _holding("TCS",  qty=5,  last=3000.0)],
        ))
        from src.portfolio_intelligence.service import get_portfolio_exposure_breakdown
        result = get_portfolio_exposure_breakdown()
        assert result["long_positions"] == 2
        assert result["short_positions"] == 0
        assert result["short_exposure"] == 0.0
        assert result["long_exposure"] == round(10 * 1500.0 + 5 * 3000.0, 2)

    def test_short_position_in_exposure(self, monkeypatch):
        import src.broker as broker_mod
        monkeypatch.setattr(broker_mod, "get_broker", lambda: _fake_broker(
            positions=[_position("NIFTY", qty=-2, last=22000.0)],
        ))
        from src.portfolio_intelligence.service import get_portfolio_exposure_breakdown
        result = get_portfolio_exposure_breakdown()
        assert result["short_positions"] == 1
        assert result["short_exposure"] == round(2 * 22000.0, 2)
        assert result["net_exposure"] < 0

    def test_largest_position_identified(self, monkeypatch):
        import src.broker as broker_mod
        monkeypatch.setattr(broker_mod, "get_broker", lambda: _fake_broker(
            holdings=[
                _holding("SMALL", qty=1,   last=100.0),
                _holding("BIG",   qty=100, last=3000.0),
            ],
        ))
        from src.portfolio_intelligence.service import get_portfolio_exposure_breakdown
        result = get_portfolio_exposure_breakdown()
        assert result["largest_position"]["symbol"] == "BIG"

    def test_top_exposures_max_5(self, monkeypatch):
        import src.broker as broker_mod
        monkeypatch.setattr(broker_mod, "get_broker", lambda: _fake_broker(
            holdings=[_holding(f"S{i}", qty=10, last=float(100 + i * 50)) for i in range(8)],
        ))
        from src.portfolio_intelligence.service import get_portfolio_exposure_breakdown
        result = get_portfolio_exposure_breakdown()
        assert len(result["top_exposures"]) == 5

    def test_concentration_metrics_present(self, monkeypatch):
        import src.broker as broker_mod
        monkeypatch.setattr(broker_mod, "get_broker", lambda: _fake_broker(
            holdings=[_holding("INFY", qty=10, last=1500.0)],
        ))
        from src.portfolio_intelligence.service import get_portfolio_exposure_breakdown
        result = get_portfolio_exposure_breakdown()
        cm = result["concentration_metrics"]
        assert "max_single_position_pct" in cm
        assert "diversification_score" in cm
        assert "concentrated" in cm

    def test_pct_of_portfolio_in_largest(self, monkeypatch):
        import src.broker as broker_mod
        monkeypatch.setattr(broker_mod, "get_broker", lambda: _fake_broker(
            holdings=[
                _holding("A", qty=1, last=6000.0),
                _holding("B", qty=1, last=4000.0),
            ],
        ))
        from src.portfolio_intelligence.service import get_portfolio_exposure_breakdown
        result = get_portfolio_exposure_breakdown()
        assert result["largest_position"]["pct_of_portfolio"] == 60.0

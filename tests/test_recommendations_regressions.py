"""Regression tests for Phase 13 — Trade Recommendation Engine.

RR-1  recommend_trade never mutates plan dict
RR-2  _apply_size_factors min-floor (always >= 1)
RR-3  get_daily_brief falls back gracefully on every market_context call
RR-4  review_open_trades uses "action" key (not "review_action")
RR-5  recommend_trade returns "error" key when _create_trade_plan raises
"""
from __future__ import annotations

import pytest
import src.recommendations.engine as rec_engine
from src.recommendations.engine import _apply_size_factors, _direction_from_signal


# ---------------------------------------------------------------------------
# RR-1: recommend_trade does not mutate the plan dict returned by create_trade_plan
# ---------------------------------------------------------------------------

class TestRR1PlanImmutability:
    def test_plan_dict_not_mutated(self, monkeypatch):
        original_plan = {
            "symbol": "INFY",
            "signal": "BUY",
            "trade_allowed": True,
            "trade_quality": "HIGH_QUALITY",
            "confidence": 75,
            "entry": 1540.0,
            "stoploss": 1490.0,
            "target": 1640.0,
            "risk_reward": {"rr": 2.0, "risk": 50.0, "reward": 100.0},
            "position": {"position_size": 6, "capital": 100_000, "risk_percent": 1.0},
            "strategy": {"recommended": "Bull Call Spread", "secondary": None, "reason": "..."},
            "market_context": {"regime": "BULL_TREND"},
            "risk_score": None,
            "summary": "Enter above 1540.",
        }
        captured = {"plan": None}

        def _mock_plan(s, capital, risk_percent):
            captured["plan"] = original_plan.copy()
            return original_plan

        monkeypatch.setattr(rec_engine, "_get_open_trades", lambda s: {"count": 0, "trades": []})
        monkeypatch.setattr(rec_engine, "_create_trade_plan", _mock_plan)
        monkeypatch.setattr(rec_engine, "_get_event_risk",
                            lambda s: {"event_risk_score": 35, "event_risk_rating": "LOW"})
        monkeypatch.setattr(rec_engine, "_get_india_vix",
                            lambda: {"vix": 14.2, "caution_level": "LOW"})

        rec_engine.recommend_trade("INFY")

        # plan dict must be unchanged after the call
        assert original_plan["signal"] == "BUY"
        assert original_plan["trade_allowed"] is True
        assert original_plan["position"] == {"position_size": 6, "capital": 100_000, "risk_percent": 1.0}


# ---------------------------------------------------------------------------
# RR-2: _apply_size_factors always returns >= 1 (floor), never 0 or negative
# ---------------------------------------------------------------------------

class TestRR2SizeFactorFloor:
    def test_zero_base_returns_none(self):
        # base_size=0 would be suspicious; None input means no sizing
        result = _apply_size_factors(None, [0.01])
        assert result is None

    def test_single_factor_floor(self):
        # 1 * 0.01 = 0.01 → should floor to 1
        result = _apply_size_factors(1, [0.01])
        assert result == 1

    def test_two_factors_floor(self):
        # 2 * 0.10 * 0.10 = 0.02 → should floor to 1
        result = _apply_size_factors(2, [0.10, 0.10])
        assert result == 1

    def test_stacking_does_not_produce_zero(self):
        result = _apply_size_factors(1, [0.70, 0.50])
        assert result >= 1

    def test_normal_stacking(self):
        # 20 * 0.70 * 0.50 = 7.0
        result = _apply_size_factors(20, [0.70, 0.50])
        assert result == 7

    def test_no_factors_returns_base(self):
        result = _apply_size_factors(10, [])
        assert result == 10

    def test_large_base_stacking(self):
        # 100 * 0.70 * 0.50 = 35
        result = _apply_size_factors(100, [0.70, 0.50])
        assert result == 35


# ---------------------------------------------------------------------------
# RR-3: get_daily_brief degrades gracefully when all market_context calls fail
# ---------------------------------------------------------------------------

class TestRR3DailyBriefGracefulDegradation:
    def _all_failing(self, monkeypatch):
        monkeypatch.setattr(rec_engine, "review_open_trades",
                            lambda: {"count": 0, "needs_attention": 0, "positions": [],
                                     "summary": {"total_open": 0, "hold": 0, "reduce": 0,
                                                 "exit": 0, "total_unrealised_pnl": 0.0,
                                                 "at_risk_count": 0}})
        monkeypatch.setattr(rec_engine, "_get_india_vix",
                            lambda: (_ for _ in ()).throw(RuntimeError("vix down")))
        monkeypatch.setattr(rec_engine, "_get_market_risk_score",
                            lambda: (_ for _ in ()).throw(RuntimeError("risk down")))
        monkeypatch.setattr(rec_engine, "_get_global_pulse",
                            lambda: (_ for _ in ()).throw(RuntimeError("pulse down")))
        monkeypatch.setattr(rec_engine, "_get_upcoming_events",
                            lambda days_ahead: (_ for _ in ()).throw(RuntimeError("events down")))

    def test_no_top_level_error_when_all_market_calls_fail(self, monkeypatch):
        self._all_failing(monkeypatch)
        result = rec_engine.get_daily_brief()
        assert "error" not in result

    def test_all_market_context_fields_present_and_none(self, monkeypatch):
        self._all_failing(monkeypatch)
        result = rec_engine.get_daily_brief()
        mc = result["market_context"]
        assert mc["vix"] is None
        assert mc["vix_caution"] is None
        assert mc["overall_risk_score"] is None
        assert mc["overall_risk_rating"] is None
        assert mc["global_sentiment"] is None
        assert mc["upcoming_events"] == []

    def test_summary_still_returned_as_string(self, monkeypatch):
        self._all_failing(monkeypatch)
        result = rec_engine.get_daily_brief()
        assert isinstance(result["summary"], str)

    def test_date_always_present(self, monkeypatch):
        self._all_failing(monkeypatch)
        result = rec_engine.get_daily_brief()
        from datetime import date
        assert result["date"] == date.today().isoformat()

    def test_alerts_list_always_present(self, monkeypatch):
        self._all_failing(monkeypatch)
        result = rec_engine.get_daily_brief()
        assert isinstance(result["alerts"], list)


# ---------------------------------------------------------------------------
# RR-4: review_open_trades uses "action" key from _review_trade (not "review_action")
# ---------------------------------------------------------------------------

class TestRR4ReviewActionKey:
    def test_action_key_used_correctly(self, monkeypatch):
        review_response = {
            "symbol": "INFY",
            "direction": "LONG",
            "current_price": 1580.0,
            "current_signal": "BUY",
            "current_regime": "BULL_TREND",
            "thesis_status": "VALID",
            "action": "HOLD",         # correct key
            "current_pnl_percent": 2.6,
            "holding_days": 3,
            "summary": "...",
            # "review_action" is NOT present — regression guard
        }
        monkeypatch.setattr(rec_engine, "_get_open_trades",
                            lambda: {"count": 1, "trades": [{
                                "trade_id": "TRD-aaaa0001",
                                "symbol": "INFY",
                                "direction": "LONG",
                                "entry_price": 1540.0,
                                "quantity": 10,
                                "stoploss": 1490.0,
                                "target": 1640.0,
                                "entry_date": "2026-06-15",
                                "strategy": None,
                            }]})
        monkeypatch.setattr(rec_engine, "_review_trade",
                            lambda symbol, direction, entry_price, holding_days: review_response)

        result = rec_engine.review_open_trades()
        assert result["positions"][0]["action"] == "HOLD"

    def test_review_action_key_absent_from_response(self, monkeypatch):
        review_response = {
            "symbol": "INFY",
            "direction": "LONG",
            "current_price": 1580.0,
            "current_signal": "BUY",
            "current_regime": "BULL_TREND",
            "thesis_status": "VALID",
            "action": "HOLD",
            "current_pnl_percent": 2.6,
            "holding_days": 3,
            "summary": "...",
        }
        monkeypatch.setattr(rec_engine, "_get_open_trades",
                            lambda: {"count": 1, "trades": [{
                                "trade_id": "TRD-aaaa0001",
                                "symbol": "INFY",
                                "direction": "LONG",
                                "entry_price": 1540.0,
                                "quantity": 10,
                                "stoploss": 1490.0,
                                "target": 1640.0,
                                "entry_date": "2026-06-15",
                                "strategy": None,
                            }]})
        monkeypatch.setattr(rec_engine, "_review_trade",
                            lambda symbol, direction, entry_price, holding_days: review_response)

        result = rec_engine.review_open_trades()
        pos = result["positions"][0]
        assert "review_action" not in pos

    def test_exit_action_increments_needs_attention(self, monkeypatch):
        review_response = {
            "symbol": "INFY",
            "direction": "LONG",
            "current_price": 1400.0,
            "current_signal": "SELL",
            "current_regime": "BEAR_TREND",
            "thesis_status": "INVALIDATED",
            "action": "EXIT",
            "current_pnl_percent": -9.0,
            "holding_days": 7,
            "summary": "...",
        }
        monkeypatch.setattr(rec_engine, "_get_open_trades",
                            lambda: {"count": 1, "trades": [{
                                "trade_id": "TRD-aaaa0001",
                                "symbol": "INFY",
                                "direction": "LONG",
                                "entry_price": 1540.0,
                                "quantity": 10,
                                "stoploss": 1490.0,
                                "target": 1640.0,
                                "entry_date": "2026-06-15",
                                "strategy": None,
                            }]})
        monkeypatch.setattr(rec_engine, "_review_trade",
                            lambda symbol, direction, entry_price, holding_days: review_response)

        result = rec_engine.review_open_trades()
        assert result["needs_attention"] == 1


# ---------------------------------------------------------------------------
# RR-5: recommend_trade returns {"error": ...} when _create_trade_plan returns error
# ---------------------------------------------------------------------------

class TestRR5TradeplanErrorPropagation:
    def test_error_dict_returned_on_plan_error(self, monkeypatch):
        monkeypatch.setattr(rec_engine, "_get_open_trades", lambda s: {"count": 0, "trades": []})
        monkeypatch.setattr(rec_engine, "_create_trade_plan",
                            lambda s, capital, risk_percent: {"error": "yfinance timeout", "symbol": "INFY"})
        monkeypatch.setattr(rec_engine, "_get_event_risk",
                            lambda s: {"event_risk_score": 35, "event_risk_rating": "LOW"})
        monkeypatch.setattr(rec_engine, "_get_india_vix",
                            lambda: {"vix": 14.2, "caution_level": "LOW"})

        result = rec_engine.recommend_trade("INFY")
        assert "error" in result

    def test_no_recommendation_key_on_plan_error(self, monkeypatch):
        monkeypatch.setattr(rec_engine, "_get_open_trades", lambda s: {"count": 0, "trades": []})
        monkeypatch.setattr(rec_engine, "_create_trade_plan",
                            lambda s, capital, risk_percent: {"error": "yfinance timeout", "symbol": "INFY"})
        monkeypatch.setattr(rec_engine, "_get_event_risk",
                            lambda s: {"event_risk_score": 35, "event_risk_rating": "LOW"})
        monkeypatch.setattr(rec_engine, "_get_india_vix",
                            lambda: {"vix": 14.2, "caution_level": "LOW"})

        result = rec_engine.recommend_trade("INFY")
        assert "recommendation" not in result

    def test_symbol_preserved_on_plan_error(self, monkeypatch):
        monkeypatch.setattr(rec_engine, "_get_open_trades", lambda s: {"count": 0, "trades": []})
        monkeypatch.setattr(rec_engine, "_create_trade_plan",
                            lambda s, capital, risk_percent: {"error": "yfinance timeout", "symbol": "INFY"})
        monkeypatch.setattr(rec_engine, "_get_event_risk",
                            lambda s: {"event_risk_score": 35, "event_risk_rating": "LOW"})
        monkeypatch.setattr(rec_engine, "_get_india_vix",
                            lambda: {"vix": 14.2, "caution_level": "LOW"})

        result = rec_engine.recommend_trade("INFY")
        assert result.get("symbol") == "INFY"

    def test_exception_in_plan_also_returns_error(self, monkeypatch):
        monkeypatch.setattr(rec_engine, "_get_open_trades", lambda s: {"count": 0, "trades": []})
        monkeypatch.setattr(rec_engine, "_create_trade_plan",
                            lambda s, capital, risk_percent: (_ for _ in ()).throw(RuntimeError("network err")))
        monkeypatch.setattr(rec_engine, "_get_event_risk",
                            lambda s: {"event_risk_score": 35, "event_risk_rating": "LOW"})
        monkeypatch.setattr(rec_engine, "_get_india_vix",
                            lambda: {"vix": 14.2, "caution_level": "LOW"})

        result = rec_engine.recommend_trade("INFY")
        assert "error" in result


# ---------------------------------------------------------------------------
# RR-EXTRA: _direction_from_signal correctness
# ---------------------------------------------------------------------------

class TestDirectionFromSignal:
    def test_buy_to_long(self):
        assert _direction_from_signal("BUY") == "LONG"

    def test_neutral_bullish_to_long(self):
        assert _direction_from_signal("NEUTRAL_BULLISH") == "LONG"

    def test_sell_to_short(self):
        assert _direction_from_signal("SELL") == "SHORT"

    def test_neutral_bearish_to_short(self):
        assert _direction_from_signal("NEUTRAL_BEARISH") == "SHORT"

    def test_neutral_to_none(self):
        assert _direction_from_signal("NEUTRAL") is None

    def test_unknown_to_none(self):
        assert _direction_from_signal("UNKNOWN") is None

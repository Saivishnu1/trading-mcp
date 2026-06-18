"""Tests for src/recommendations/engine.py"""
from __future__ import annotations

import pytest
import src.recommendations.engine as rec_engine


# ---------------------------------------------------------------------------
# Mock factories
# ---------------------------------------------------------------------------

def _plan(
    signal="BUY",
    trade_allowed=True,
    entry=1540.0,
    stoploss=1490.0,
    target=1640.0,
    rr=2.0,
    quality="HIGH_QUALITY",
    regime="BULL_TREND",
    position_size=6,
):
    if signal == "NEUTRAL":
        return {
            "symbol": "INFY",
            "signal": signal,
            "trade_allowed": False,
            "reason": "No trade.",
            "market_context": {"regime": None},
            "risk_score": None,
            "summary": "No trade recommended.",
        }
    return {
        "symbol": "INFY",
        "signal": signal,
        "trade_allowed": trade_allowed,
        "trade_quality": quality,
        "confidence": 75,
        "entry": entry,
        "stoploss": stoploss,
        "target": target,
        "risk_reward": {"rr": rr, "risk": 50.0, "reward": 100.0},
        "position": {
            "position_size": position_size,
            "capital": 100_000,
            "risk_percent": 1.0,
            "risk_amount": 1000.0,
        },
        "strategy": {"recommended": "Bull Call Spread", "secondary": None, "reason": "..."},
        "market_context": {"regime": regime},
        "risk_score": None,
        "summary": "Enter above 1540.",
    }


def _event_risk(score=35, rating="LOW"):
    return {
        "event_risk_score": score,
        "event_risk_rating": rating,
        "confidence": 1.0,
        "factors": [],
    }


def _vix(caution="LOW", vix=14.2):
    return {"vix": vix, "caution_level": caution, "percentile": 30.0}


def _open_trades(trades=None):
    t = trades or []
    return {"count": len(t), "trades": t}


def _open_trade(symbol="INFY", direction="LONG", entry_price=1540.0, trade_id="TRD-aaaabbbb"):
    return {
        "trade_id": trade_id,
        "symbol": symbol,
        "direction": direction,
        "entry_price": entry_price,
        "quantity": 10,
        "status": "OPEN",
        "entry_date": "2026-06-15",
        "stoploss": 1490.0,
        "target": 1640.0,
    }


def _review(
    action="HOLD",
    thesis="VALID",
    signal="BUY",
    regime="BULL_TREND",
    price=1580.0,
    pnl_pct=2.6,
):
    return {
        "symbol": "INFY",
        "direction": "LONG",
        "current_price": price,
        "current_signal": signal,
        "current_regime": regime,
        "thesis_status": thesis,
        "action": action,
        "current_pnl_percent": pnl_pct,
        "holding_days": 3,
        "summary": "...",
    }


# ---------------------------------------------------------------------------
# TestRecommendTrade
# ---------------------------------------------------------------------------

class TestRecommendTrade:
    def _call(self, monkeypatch, symbol="INFY", trades=None,
              plan=None, er=None, vix_data=None):
        monkeypatch.setattr(rec_engine, "_get_open_trades", lambda s: _open_trades(trades))
        monkeypatch.setattr(rec_engine, "_create_trade_plan", lambda s, capital, risk_percent: plan or _plan())
        monkeypatch.setattr(rec_engine, "_get_event_risk", lambda s: er if er is not None else _event_risk())
        monkeypatch.setattr(rec_engine, "_get_india_vix", lambda: vix_data if vix_data is not None else _vix())
        return rec_engine.recommend_trade(symbol)

    def test_enter_on_buy_signal(self, monkeypatch):
        result = self._call(monkeypatch)
        assert result["recommendation"] == "ENTER"
        assert result["trade_allowed"] is True

    def test_avoid_on_neutral_signal(self, monkeypatch):
        result = self._call(monkeypatch, plan=_plan(signal="NEUTRAL"))
        assert result["recommendation"] == "AVOID"
        assert result["trade_allowed"] is False

    def test_avoid_on_extreme_event_risk(self, monkeypatch):
        result = self._call(monkeypatch, er=_event_risk(score=85, rating="EXTREME"))
        assert result["recommendation"] == "AVOID"
        assert result["trade_allowed"] is False

    def test_wait_on_high_event_risk(self, monkeypatch):
        result = self._call(monkeypatch, er=_event_risk(score=65, rating="HIGH"))
        assert result["recommendation"] == "WAIT"
        assert result["trade_allowed"] is True

    def test_position_size_reduced_on_high_event_risk(self, monkeypatch):
        result = self._call(monkeypatch, er=_event_risk(score=65, rating="HIGH"),
                            plan=_plan(position_size=10))
        assert result["position_size"] == 7  # 10 * 0.70 = 7

    def test_duplicate_exposure_flagged(self, monkeypatch):
        trades = [_open_trade(direction="LONG")]
        result = self._call(monkeypatch, trades=trades)
        assert result["duplicate_exposure"] is True

    def test_wait_on_duplicate_exposure(self, monkeypatch):
        trades = [_open_trade(direction="LONG")]
        result = self._call(monkeypatch, trades=trades)
        assert result["recommendation"] == "WAIT"

    def test_position_size_halved_on_duplicate(self, monkeypatch):
        trades = [_open_trade(direction="LONG")]
        result = self._call(monkeypatch, trades=trades, plan=_plan(position_size=10))
        assert result["position_size"] == 5  # 10 * 0.50 = 5

    def test_opposite_direction_not_duplicate(self, monkeypatch):
        trades = [_open_trade(direction="SHORT")]
        result = self._call(monkeypatch, trades=trades, plan=_plan(signal="BUY"))
        assert result["duplicate_exposure"] is False

    def test_two_same_direction_listed_in_existing(self, monkeypatch):
        trades = [_open_trade(trade_id="TRD-00000001"), _open_trade(trade_id="TRD-00000002")]
        result = self._call(monkeypatch, trades=trades)
        assert len(result["existing_open_trades"]) == 2
        assert result["duplicate_exposure"] is True

    def test_avoid_on_vix_extreme(self, monkeypatch):
        result = self._call(monkeypatch, vix_data=_vix(caution="EXTREME", vix=30.0))
        assert result["recommendation"] == "AVOID"
        assert result["trade_allowed"] is False

    def test_wait_on_vix_high(self, monkeypatch):
        result = self._call(monkeypatch, vix_data=_vix(caution="HIGH", vix=22.0))
        assert result["recommendation"] == "WAIT"

    def test_event_risk_null_when_fetch_fails(self, monkeypatch):
        monkeypatch.setattr(rec_engine, "_get_open_trades", lambda s: _open_trades())
        monkeypatch.setattr(rec_engine, "_create_trade_plan", lambda s, capital, risk_percent: _plan())
        monkeypatch.setattr(rec_engine, "_get_event_risk", lambda s: (_ for _ in ()).throw(RuntimeError("unavailable")))
        monkeypatch.setattr(rec_engine, "_get_india_vix", lambda: _vix())
        result = rec_engine.recommend_trade("INFY")
        assert result["event_risk_score"] is None

    def test_vix_null_when_fetch_fails(self, monkeypatch):
        monkeypatch.setattr(rec_engine, "_get_open_trades", lambda s: _open_trades())
        monkeypatch.setattr(rec_engine, "_create_trade_plan", lambda s, capital, risk_percent: _plan())
        monkeypatch.setattr(rec_engine, "_get_event_risk", lambda s: _event_risk())
        monkeypatch.setattr(rec_engine, "_get_india_vix", lambda: (_ for _ in ()).throw(RuntimeError("unavailable")))
        result = rec_engine.recommend_trade("INFY")
        assert result["vix_caution"] is None

    def test_direction_long_on_buy(self, monkeypatch):
        result = self._call(monkeypatch, plan=_plan(signal="BUY"))
        assert result["direction"] == "LONG"

    def test_direction_short_on_sell(self, monkeypatch):
        result = self._call(monkeypatch, plan=_plan(signal="SELL"))
        assert result["direction"] == "SHORT"

    def test_direction_none_on_neutral(self, monkeypatch):
        result = self._call(monkeypatch, plan=_plan(signal="NEUTRAL"))
        assert result["direction"] is None

    def test_symbol_uppercased(self, monkeypatch):
        result = self._call(monkeypatch, symbol="infy")
        assert result["symbol"] == "INFY"

    def test_all_expected_keys_present(self, monkeypatch):
        result = self._call(monkeypatch)
        for key in (
            "symbol", "recommendation", "trade_allowed", "direction", "regime",
            "signal", "entry", "stoploss", "target", "risk_reward", "position_size",
            "strategy", "trade_quality", "event_risk_score", "event_risk_rating",
            "vix", "vix_caution", "duplicate_exposure", "existing_open_trades",
            "cautions", "reasons", "risk_adjustments",
        ):
            assert key in result, f"missing key: {key}"

    def test_reasons_populated(self, monkeypatch):
        result = self._call(monkeypatch)
        assert len(result["reasons"]) > 0

    def test_stacking_adjustments(self, monkeypatch):
        # event risk HIGH (×0.70) + duplicate (×0.50) on base 20
        trades = [_open_trade(direction="LONG")]
        result = self._call(
            monkeypatch,
            trades=trades,
            plan=_plan(position_size=20),
            er=_event_risk(score=65, rating="HIGH"),
        )
        # 20 * 0.70 * 0.50 = 7
        assert result["position_size"] == 7

    def test_create_trade_plan_error_propagated(self, monkeypatch):
        monkeypatch.setattr(rec_engine, "_get_open_trades", lambda s: _open_trades())
        monkeypatch.setattr(rec_engine, "_create_trade_plan",
                            lambda s, capital, risk_percent: {"error": "data unavailable", "symbol": "INFY"})
        monkeypatch.setattr(rec_engine, "_get_event_risk", lambda s: _event_risk())
        monkeypatch.setattr(rec_engine, "_get_india_vix", lambda: _vix())
        result = rec_engine.recommend_trade("INFY")
        assert "error" in result


# ---------------------------------------------------------------------------
# TestReviewOpenTrades
# ---------------------------------------------------------------------------

class TestReviewOpenTrades:
    def _setup(self, monkeypatch, trades=None, review_fn=None):
        monkeypatch.setattr(rec_engine, "_get_open_trades", lambda: _open_trades(trades))
        if review_fn is None:
            monkeypatch.setattr(rec_engine, "_review_trade",
                                lambda symbol, direction, entry_price, holding_days: _review())
        else:
            # wrap so positional-style (s, d, e, h) fns work when engine calls with kwargs
            _fn = review_fn
            monkeypatch.setattr(rec_engine, "_review_trade",
                                lambda symbol, direction, entry_price, holding_days: _fn(symbol, direction, entry_price, holding_days))

    def test_no_open_trades(self, monkeypatch):
        self._setup(monkeypatch)
        result = rec_engine.review_open_trades()
        assert result["count"] == 0
        assert result["positions"] == []

    def test_one_hold_position(self, monkeypatch):
        self._setup(monkeypatch, trades=[_open_trade()])
        result = rec_engine.review_open_trades()
        assert result["count"] == 1
        assert result["positions"][0]["action"] == "HOLD"

    def test_exit_increments_needs_attention(self, monkeypatch):
        self._setup(monkeypatch, trades=[_open_trade()],
                    review_fn=lambda s, d, e, h: _review(action="EXIT"))
        result = rec_engine.review_open_trades()
        assert result["needs_attention"] == 1

    def test_reduce_increments_needs_attention(self, monkeypatch):
        self._setup(monkeypatch, trades=[_open_trade()],
                    review_fn=lambda s, d, e, h: _review(action="REDUCE"))
        result = rec_engine.review_open_trades()
        assert result["needs_attention"] == 1

    def test_stoploss_breached_long(self, monkeypatch):
        trade = _open_trade()
        trade["stoploss"] = 1490.0
        self._setup(monkeypatch, trades=[trade],
                    review_fn=lambda s, d, e, h: _review(price=1480.0, pnl_pct=-3.9))
        result = rec_engine.review_open_trades()
        assert result["positions"][0]["stoploss_breached"] is True
        assert result["summary"]["at_risk_count"] == 1

    def test_target_reached_long(self, monkeypatch):
        trade = _open_trade()
        trade["target"] = 1640.0
        self._setup(monkeypatch, trades=[trade],
                    review_fn=lambda s, d, e, h: _review(price=1650.0, pnl_pct=7.1))
        result = rec_engine.review_open_trades()
        assert result["positions"][0]["target_reached"] is True

    def test_stoploss_breached_short(self, monkeypatch):
        trade = _open_trade(direction="SHORT")
        trade["stoploss"] = 1600.0
        trade["direction"] = "SHORT"
        self._setup(monkeypatch, trades=[trade],
                    review_fn=lambda s, d, e, h: _review(price=1620.0, pnl_pct=-5.2))
        result = rec_engine.review_open_trades()
        pos = result["positions"][0]
        assert pos["stoploss_breached"] is True

    def test_target_reached_short(self, monkeypatch):
        trade = _open_trade(direction="SHORT")
        trade["target"] = 1400.0
        trade["direction"] = "SHORT"
        self._setup(monkeypatch, trades=[trade],
                    review_fn=lambda s, d, e, h: _review(price=1390.0, pnl_pct=9.1))
        result = rec_engine.review_open_trades()
        assert result["positions"][0]["target_reached"] is True

    def test_current_pnl_long_profit(self, monkeypatch):
        trade = _open_trade(entry_price=1000.0)
        trade["quantity"] = 10
        self._setup(monkeypatch, trades=[trade],
                    review_fn=lambda s, d, e, h: _review(price=1100.0, pnl_pct=10.0))
        result = rec_engine.review_open_trades()
        assert result["positions"][0]["current_pnl"] == 1000.0

    def test_current_pnl_quantity_none_defaults_to_1(self, monkeypatch):
        trade = _open_trade(entry_price=1000.0)
        trade["quantity"] = None
        self._setup(monkeypatch, trades=[trade],
                    review_fn=lambda s, d, e, h: _review(price=1100.0, pnl_pct=10.0))
        result = rec_engine.review_open_trades()
        assert result["positions"][0]["current_pnl"] == 100.0

    def test_total_unrealised_pnl(self, monkeypatch):
        trades = [
            _open_trade(trade_id="TRD-00000001", entry_price=1000.0),
            _open_trade(trade_id="TRD-00000002", entry_price=2000.0),
        ]
        for t in trades:
            t["quantity"] = 1
        call_count = [0]
        def _rev(s, d, e, h):
            call_count[0] += 1
            prices = {1000.0: 1100.0, 2000.0: 2200.0}
            p = prices.get(e, e)
            pct = (p - e) / e * 100
            return _review(price=p, pnl_pct=pct)
        self._setup(monkeypatch, trades=trades, review_fn=_rev)
        result = rec_engine.review_open_trades()
        # 100 + 200 = 300
        assert result["summary"]["total_unrealised_pnl"] == 300.0

    def test_per_position_error_isolation(self, monkeypatch):
        trades = [
            _open_trade(symbol="INFY", trade_id="TRD-aaaa0001"),
            _open_trade(symbol="TCS", trade_id="TRD-aaaa0002"),
        ]
        call_count = [0]
        def _rev(s, d, e, h):
            call_count[0] += 1
            if s == "INFY":
                raise RuntimeError("fetch failed")
            return _review()
        self._setup(monkeypatch, trades=trades, review_fn=_rev)
        result = rec_engine.review_open_trades()
        assert result["count"] == 2
        infy = next(p for p in result["positions"] if p["symbol"] == "INFY")
        tcs = next(p for p in result["positions"] if p["symbol"] == "TCS")
        assert infy["error"] is not None
        assert tcs["error"] is None
        assert tcs["action"] == "HOLD"

    def test_summary_action_counts(self, monkeypatch):
        trades = [
            _open_trade(trade_id="TRD-00000001"),
            _open_trade(trade_id="TRD-00000002"),
            _open_trade(trade_id="TRD-00000003"),
        ]
        actions = ["HOLD", "REDUCE", "EXIT"]
        idx = [0]
        def _rev(s, d, e, h):
            action = actions[idx[0] % 3]
            idx[0] += 1
            return _review(action=action)
        self._setup(monkeypatch, trades=trades, review_fn=_rev)
        result = rec_engine.review_open_trades()
        s = result["summary"]
        assert s["hold"] == 1
        assert s["reduce"] == 1
        assert s["exit"] == 1

    def test_stoploss_none_never_breached(self, monkeypatch):
        trade = _open_trade()
        trade["stoploss"] = None
        self._setup(monkeypatch, trades=[trade],
                    review_fn=lambda s, d, e, h: _review(price=1000.0))
        result = rec_engine.review_open_trades()
        assert result["positions"][0]["stoploss_breached"] is False

    def test_get_open_trades_error_propagated(self, monkeypatch):
        monkeypatch.setattr(rec_engine, "_get_open_trades", lambda: {"error": "journal db down"})
        result = rec_engine.review_open_trades()
        assert "error" in result
        assert "journal db down" in result["error"]

    def test_all_position_keys_present(self, monkeypatch):
        self._setup(monkeypatch, trades=[_open_trade()])
        result = rec_engine.review_open_trades()
        pos = result["positions"][0]
        for key in (
            "trade_id", "symbol", "direction", "entry_price", "quantity",
            "stoploss", "target", "entry_date", "strategy",
            "current_price", "current_pnl", "current_pnl_percent",
            "days_held", "action", "thesis_status",
            "current_regime", "current_signal",
            "stoploss_breached", "target_reached", "error",
        ):
            assert key in pos, f"missing key: {key}"

    def test_current_regime_and_signal_populated(self, monkeypatch):
        self._setup(monkeypatch, trades=[_open_trade()],
                    review_fn=lambda s, d, e, h: _review(regime="BEAR_TREND", signal="SELL"))
        result = rec_engine.review_open_trades()
        pos = result["positions"][0]
        assert pos["current_regime"] == "BEAR_TREND"
        assert pos["current_signal"] == "SELL"

    def test_days_held_computed_today(self, monkeypatch):
        from datetime import date
        today = date.today().isoformat()
        trade = _open_trade()
        trade["entry_date"] = today
        self._setup(monkeypatch, trades=[trade])
        result = rec_engine.review_open_trades()
        assert result["positions"][0]["days_held"] == 0

    def test_response_has_required_keys(self, monkeypatch):
        self._setup(monkeypatch)
        result = rec_engine.review_open_trades()
        for key in ("count", "needs_attention", "positions", "summary"):
            assert key in result

    def test_summary_keys_present(self, monkeypatch):
        self._setup(monkeypatch)
        result = rec_engine.review_open_trades()
        s = result["summary"]
        for key in ("total_open", "hold", "reduce", "exit", "total_unrealised_pnl", "at_risk_count"):
            assert key in s

    def test_two_positions_mixed(self, monkeypatch):
        trades = [
            _open_trade(trade_id="TRD-00000001"),
            _open_trade(trade_id="TRD-00000002"),
        ]
        actions = ["HOLD", "EXIT"]
        idx = [0]
        def _rev(s, d, e, h):
            a = actions[idx[0] % 2]
            idx[0] += 1
            return _review(action=a)
        self._setup(monkeypatch, trades=trades, review_fn=_rev)
        result = rec_engine.review_open_trades()
        assert result["count"] == 2
        assert result["needs_attention"] == 1


# ---------------------------------------------------------------------------
# TestGatingDataUnavailable
# ---------------------------------------------------------------------------

class TestGatingDataUnavailable:
    """
    Fix 6: Silent except-pass on event_risk/VIX fetch now surfaces as cautions
    and sets gating_data_available flags to False.
    """

    def test_event_risk_fetch_failure_adds_caution(self, monkeypatch):
        monkeypatch.setattr(rec_engine, "_get_open_trades", lambda s: _open_trades())
        monkeypatch.setattr(rec_engine, "_create_trade_plan",
                            lambda s, capital, risk_percent: _plan())
        monkeypatch.setattr(rec_engine, "_get_event_risk",
                            lambda s: (_ for _ in ()).throw(RuntimeError("network error")))
        monkeypatch.setattr(rec_engine, "_get_india_vix", lambda: _vix())
        result = rec_engine.recommend_trade("INFY")
        assert "error" not in result
        assert any("event risk" in c.lower() for c in result["cautions"])
        assert result["gating_data_available"]["event_risk"] is False

    def test_vix_fetch_failure_adds_caution(self, monkeypatch):
        monkeypatch.setattr(rec_engine, "_get_open_trades", lambda s: _open_trades())
        monkeypatch.setattr(rec_engine, "_create_trade_plan",
                            lambda s, capital, risk_percent: _plan())
        monkeypatch.setattr(rec_engine, "_get_event_risk", lambda s: _event_risk())
        monkeypatch.setattr(rec_engine, "_get_india_vix",
                            lambda: (_ for _ in ()).throw(RuntimeError("network error")))
        result = rec_engine.recommend_trade("INFY")
        assert "error" not in result
        assert any("vix" in c.lower() for c in result["cautions"])
        assert result["gating_data_available"]["vix"] is False

    def test_gating_data_available_true_when_both_succeed(self, monkeypatch):
        monkeypatch.setattr(rec_engine, "_get_open_trades", lambda s: _open_trades())
        monkeypatch.setattr(rec_engine, "_create_trade_plan",
                            lambda s, capital, risk_percent: _plan())
        monkeypatch.setattr(rec_engine, "_get_event_risk", lambda s: _event_risk())
        monkeypatch.setattr(rec_engine, "_get_india_vix", lambda: _vix())
        result = rec_engine.recommend_trade("INFY")
        assert result["gating_data_available"]["event_risk"] is True
        assert result["gating_data_available"]["vix"] is True



# ---------------------------------------------------------------------------
# TestGetDailyBrief
# ---------------------------------------------------------------------------

class TestGetDailyBrief:
    def _setup(self, monkeypatch, open_positions=None, vix_data=None,
               risk_data=None, pulse_data=None, events_data=None):
        if open_positions is None:
            open_positions = {
                "count": 0, "needs_attention": 0, "positions": [],
                "summary": {"total_open": 0, "hold": 0, "reduce": 0, "exit": 0,
                            "total_unrealised_pnl": 0.0, "at_risk_count": 0},
            }
        monkeypatch.setattr(rec_engine, "review_open_trades", lambda: open_positions)
        monkeypatch.setattr(rec_engine, "_get_india_vix",
                            lambda: vix_data if vix_data is not None else _vix())
        monkeypatch.setattr(rec_engine, "_get_market_risk_score",
                            lambda: risk_data if risk_data is not None else {"score": 38, "rating": "LOW"})
        monkeypatch.setattr(rec_engine, "_get_global_pulse",
                            lambda: pulse_data if pulse_data is not None else {"overall_sentiment": "RISK_ON"})
        monkeypatch.setattr(rec_engine, "_get_upcoming_events",
                            lambda days_ahead: events_data if events_data is not None else {"events": []})

    def test_returns_expected_keys(self, monkeypatch):
        self._setup(monkeypatch)
        result = rec_engine.get_daily_brief()
        for key in ("date", "market_context", "open_positions", "alerts", "summary"):
            assert key in result

    def test_date_is_today(self, monkeypatch):
        from datetime import date
        self._setup(monkeypatch)
        result = rec_engine.get_daily_brief()
        assert result["date"] == date.today().isoformat()

    def test_market_context_has_all_keys(self, monkeypatch):
        self._setup(monkeypatch)
        mc = rec_engine.get_daily_brief()["market_context"]
        for key in ("vix", "vix_caution", "overall_risk_score", "overall_risk_rating",
                    "global_sentiment", "upcoming_events"):
            assert key in mc

    def test_alerts_empty_when_all_hold(self, monkeypatch):
        self._setup(monkeypatch)
        result = rec_engine.get_daily_brief()
        assert result["alerts"] == []

    def test_alert_on_exit_position(self, monkeypatch):
        pos = {
            "trade_id": "TRD-exit0001",
            "symbol": "INFY",
            "direction": "LONG",
            "entry_price": 1540.0,
            "current_price": 1400.0,
            "action": "EXIT",
            "thesis_status": "INVALIDATED",
            "stoploss_breached": False,
        }
        open_positions = {
            "count": 1, "needs_attention": 1,
            "positions": [pos],
            "summary": {"total_open": 1, "hold": 0, "reduce": 0, "exit": 1,
                        "total_unrealised_pnl": -1400.0, "at_risk_count": 0},
        }
        self._setup(monkeypatch, open_positions=open_positions)
        result = rec_engine.get_daily_brief()
        assert any("EXIT" in a for a in result["alerts"])

    def test_alert_on_stoploss_breached(self, monkeypatch):
        pos = {
            "trade_id": "TRD-sl000001",
            "symbol": "TCS",
            "direction": "LONG",
            "current_price": 3400.0,
            "action": "HOLD",
            "thesis_status": "VALID",
            "stoploss_breached": True,
        }
        open_positions = {
            "count": 1, "needs_attention": 0,
            "positions": [pos],
            "summary": {"total_open": 1, "hold": 1, "reduce": 0, "exit": 0,
                        "total_unrealised_pnl": -500.0, "at_risk_count": 1},
        }
        self._setup(monkeypatch, open_positions=open_positions)
        result = rec_engine.get_daily_brief()
        assert any("STOPLOSS" in a for a in result["alerts"])

    def test_alert_on_high_impact_event(self, monkeypatch):
        events_data = {"events": [{"name": "RBI MPC", "impact": "HIGH", "days_until": 2}]}
        self._setup(monkeypatch, events_data=events_data)
        result = rec_engine.get_daily_brief()
        assert any("RBI MPC" in a for a in result["alerts"])

    def test_summary_non_empty(self, monkeypatch):
        self._setup(monkeypatch)
        result = rec_engine.get_daily_brief()
        assert isinstance(result["summary"], str)
        assert len(result["summary"]) > 0

    def test_vix_null_when_fetch_fails(self, monkeypatch):
        monkeypatch.setattr(rec_engine, "review_open_trades",
                            lambda: {"count": 0, "needs_attention": 0, "positions": [],
                                     "summary": {"total_open": 0, "hold": 0, "reduce": 0,
                                                 "exit": 0, "total_unrealised_pnl": 0.0, "at_risk_count": 0}})
        monkeypatch.setattr(rec_engine, "_get_india_vix",
                            lambda: (_ for _ in ()).throw(RuntimeError("vix unavailable")))
        monkeypatch.setattr(rec_engine, "_get_market_risk_score", lambda: {"score": 38, "rating": "LOW"})
        monkeypatch.setattr(rec_engine, "_get_global_pulse", lambda: {"overall_sentiment": "RISK_ON"})
        monkeypatch.setattr(rec_engine, "_get_upcoming_events", lambda days_ahead: {"events": []})
        result = rec_engine.get_daily_brief()
        assert result["market_context"]["vix"] is None
        assert "error" not in result

    def test_risk_score_null_when_fetch_fails(self, monkeypatch):
        monkeypatch.setattr(rec_engine, "review_open_trades",
                            lambda: {"count": 0, "needs_attention": 0, "positions": [],
                                     "summary": {"total_open": 0, "hold": 0, "reduce": 0,
                                                 "exit": 0, "total_unrealised_pnl": 0.0, "at_risk_count": 0}})
        monkeypatch.setattr(rec_engine, "_get_india_vix", lambda: _vix())
        monkeypatch.setattr(rec_engine, "_get_market_risk_score",
                            lambda: (_ for _ in ()).throw(RuntimeError("risk unavailable")))
        monkeypatch.setattr(rec_engine, "_get_global_pulse", lambda: {"overall_sentiment": "RISK_ON"})
        monkeypatch.setattr(rec_engine, "_get_upcoming_events", lambda days_ahead: {"events": []})
        result = rec_engine.get_daily_brief()
        assert result["market_context"]["overall_risk_score"] is None
        assert "error" not in result

    def test_global_sentiment_null_when_fetch_fails(self, monkeypatch):
        monkeypatch.setattr(rec_engine, "review_open_trades",
                            lambda: {"count": 0, "needs_attention": 0, "positions": [],
                                     "summary": {"total_open": 0, "hold": 0, "reduce": 0,
                                                 "exit": 0, "total_unrealised_pnl": 0.0, "at_risk_count": 0}})
        monkeypatch.setattr(rec_engine, "_get_india_vix", lambda: _vix())
        monkeypatch.setattr(rec_engine, "_get_market_risk_score", lambda: {"score": 38, "rating": "LOW"})
        monkeypatch.setattr(rec_engine, "_get_global_pulse",
                            lambda: (_ for _ in ()).throw(RuntimeError("pulse unavailable")))
        monkeypatch.setattr(rec_engine, "_get_upcoming_events", lambda days_ahead: {"events": []})
        result = rec_engine.get_daily_brief()
        assert result["market_context"]["global_sentiment"] is None
        assert "error" not in result

    def test_upcoming_events_empty_on_failure(self, monkeypatch):
        monkeypatch.setattr(rec_engine, "review_open_trades",
                            lambda: {"count": 0, "needs_attention": 0, "positions": [],
                                     "summary": {"total_open": 0, "hold": 0, "reduce": 0,
                                                 "exit": 0, "total_unrealised_pnl": 0.0, "at_risk_count": 0}})
        monkeypatch.setattr(rec_engine, "_get_india_vix", lambda: _vix())
        monkeypatch.setattr(rec_engine, "_get_market_risk_score", lambda: {"score": 38, "rating": "LOW"})
        monkeypatch.setattr(rec_engine, "_get_global_pulse", lambda: {"overall_sentiment": "RISK_ON"})
        monkeypatch.setattr(rec_engine, "_get_upcoming_events",
                            lambda days_ahead: (_ for _ in ()).throw(RuntimeError("events unavailable")))
        result = rec_engine.get_daily_brief()
        assert result["market_context"]["upcoming_events"] == []

    def test_no_open_trades_valid_structure(self, monkeypatch):
        self._setup(monkeypatch)
        result = rec_engine.get_daily_brief()
        assert result["open_positions"]["count"] == 0

    def test_summary_reflects_exit_count(self, monkeypatch):
        open_positions = {
            "count": 1, "needs_attention": 1,
            "positions": [{
                "trade_id": "TRD-x", "symbol": "INFY", "direction": "LONG",
                "current_price": 1400.0, "action": "EXIT",
                "thesis_status": "INVALIDATED", "stoploss_breached": False,
            }],
            "summary": {"total_open": 1, "hold": 0, "reduce": 0, "exit": 1,
                        "total_unrealised_pnl": -1400.0, "at_risk_count": 0},
        }
        self._setup(monkeypatch, open_positions=open_positions)
        result = rec_engine.get_daily_brief()
        assert "EXIT" in result["summary"]

    def test_review_open_trades_error_in_response(self, monkeypatch):
        monkeypatch.setattr(rec_engine, "review_open_trades", lambda: {"error": "journal down"})
        monkeypatch.setattr(rec_engine, "_get_india_vix", lambda: _vix())
        monkeypatch.setattr(rec_engine, "_get_market_risk_score", lambda: {"score": 38, "rating": "LOW"})
        monkeypatch.setattr(rec_engine, "_get_global_pulse", lambda: {"overall_sentiment": "RISK_ON"})
        monkeypatch.setattr(rec_engine, "_get_upcoming_events", lambda days_ahead: {"events": []})
        result = rec_engine.get_daily_brief()
        assert result["open_positions"]["error"] == "journal down"
        assert "error" not in result

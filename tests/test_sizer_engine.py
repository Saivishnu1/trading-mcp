"""Tests for src/sizer/engine.py — Phase 14 Position Sizing Engine."""
from __future__ import annotations

import math
import sqlite3

import pytest
import src.sizer.engine as sizer_engine
from src.sizer.engine import _apply_size_factors, _compute_portfolio_heat


# ---------------------------------------------------------------------------
# Mock factories
# ---------------------------------------------------------------------------

def _no_trades():
    return {"count": 0, "trades": []}


def _trades_with(*items):
    return {"count": len(items), "trades": list(items)}


def _open_trade(symbol="INFY", direction="LONG", entry_price=1540.0,
                stoploss=1490.0, quantity=10):
    return {
        "trade_id": "TRD-aaaabbbb",
        "symbol": symbol,
        "direction": direction,
        "entry_price": entry_price,
        "stoploss": stoploss,
        "quantity": quantity,
        "status": "OPEN",
    }


def _port_report(score=30, rating="LOW"):
    return {"portfolio_risk_score": score, "rating": rating, "total_positions": 1}


def _recommendation(
    signal="BUY",
    recommendation="ENTER",
    trade_allowed=True,
    entry=1540.0,
    stoploss=1490.0,
    target=1640.0,
    rr=2.0,
    position_size=6,
    direction="LONG",
    regime="BULL_TREND",
    strategy="Bull Call Spread",
    trade_quality="HIGH_QUALITY",
    event_risk_score=35,
    event_risk_rating="LOW",
    vix=14.2,
    vix_caution="LOW",
    duplicate_exposure=False,
    cautions=None,
    reasons=None,
):
    return {
        "symbol": "INFY",
        "recommendation": recommendation,
        "trade_allowed": trade_allowed,
        "direction": direction,
        "signal": signal,
        "regime": regime,
        "entry": entry,
        "stoploss": stoploss,
        "target": target,
        "risk_reward": rr,
        "position_size": position_size,
        "strategy": strategy,
        "trade_quality": trade_quality,
        "event_risk_score": event_risk_score,
        "event_risk_rating": event_risk_rating,
        "vix": vix,
        "vix_caution": vix_caution,
        "duplicate_exposure": duplicate_exposure,
        "cautions": cautions or [],
        "reasons": reasons or ["BULL_TREND regime with BUY signal"],
        "risk_adjustments": [],
    }


def _setup_no_portfolio(monkeypatch):
    monkeypatch.setattr(sizer_engine, "_get_open_trades", lambda: _no_trades())
    monkeypatch.setattr(sizer_engine, "_get_portfolio_risk_report",
                        lambda: _port_report(score=30, rating="LOW"))


# ---------------------------------------------------------------------------
# TestApplySizeFactors
# ---------------------------------------------------------------------------

class TestApplySizeFactors:
    def test_no_factors_unchanged(self):
        assert _apply_size_factors(10, []) == 10

    def test_single_factor(self):
        assert _apply_size_factors(10, [0.70]) == 7

    def test_two_factors_stack(self):
        # 20 * 0.70 * 0.50 = 7.0
        assert _apply_size_factors(20, [0.70, 0.50]) == 7

    def test_floor_at_one(self):
        assert _apply_size_factors(1, [0.01]) == 1

    def test_none_base_returns_none(self):
        assert _apply_size_factors(None, [0.70]) is None

    def test_rounding(self):
        # 3 * 0.70 = 2.1 → rounds to 2
        assert _apply_size_factors(3, [0.70]) == 2


# ---------------------------------------------------------------------------
# TestComputePortfolioHeat
# ---------------------------------------------------------------------------

class TestComputePortfolioHeat:
    def test_no_trades_returns_zero(self, monkeypatch):
        monkeypatch.setattr(sizer_engine, "_get_open_trades", lambda: _no_trades())
        heat, cautions = _compute_portfolio_heat(100_000)
        assert heat == 0.0
        assert cautions == []

    def test_long_trade_with_stoploss(self, monkeypatch):
        # risk = (1540 - 1490) * 10 = 500 → 500/100000 = 0.5%
        monkeypatch.setattr(sizer_engine, "_get_open_trades",
                            lambda: _trades_with(_open_trade()))
        heat, _ = _compute_portfolio_heat(100_000)
        assert heat == 0.5

    def test_short_trade_with_stoploss(self, monkeypatch):
        # stoploss above entry for SHORT: risk = (1600 - 1540) * 5 = 300 → 0.3%
        trade = _open_trade(direction="SHORT", entry_price=1540.0, stoploss=1600.0, quantity=5)
        monkeypatch.setattr(sizer_engine, "_get_open_trades",
                            lambda: _trades_with(trade))
        heat, _ = _compute_portfolio_heat(100_000)
        assert heat == 0.3

    def test_trade_without_stoploss_uses_default(self, monkeypatch):
        trade = _open_trade()
        trade["stoploss"] = None
        # default: 1540 * 10 * 0.02 = 308 → 0.308%
        monkeypatch.setattr(sizer_engine, "_get_open_trades",
                            lambda: _trades_with(trade))
        heat, _ = _compute_portfolio_heat(100_000)
        assert heat == 0.31  # round(308/100000*100, 2)

    def test_fetch_error_returns_zero_with_caution(self, monkeypatch):
        monkeypatch.setattr(sizer_engine, "_get_open_trades",
                            lambda: {"error": "db down"})
        heat, cautions = _compute_portfolio_heat(100_000)
        assert heat == 0.0
        assert len(cautions) == 1
        assert "db down" in cautions[0]

    def test_exception_returns_zero_with_caution(self, monkeypatch):
        monkeypatch.setattr(sizer_engine, "_get_open_trades",
                            lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        heat, cautions = _compute_portfolio_heat(100_000)
        assert heat == 0.0
        assert len(cautions) == 1

    def test_quantity_none_defaults_to_one(self, monkeypatch):
        trade = _open_trade()
        trade["quantity"] = None
        # risk = (1540 - 1490) * 1 = 50 → 0.05%
        monkeypatch.setattr(sizer_engine, "_get_open_trades",
                            lambda: _trades_with(trade))
        heat, _ = _compute_portfolio_heat(100_000)
        assert heat == 0.05

    def test_two_trades_heat_additive(self, monkeypatch):
        t1 = _open_trade(entry_price=1000.0, stoploss=900.0, quantity=5)   # risk 500 → 0.5%
        t2 = _open_trade(entry_price=2000.0, stoploss=1800.0, quantity=2)  # risk 400 → 0.4%
        monkeypatch.setattr(sizer_engine, "_get_open_trades",
                            lambda: _trades_with(t1, t2))
        heat, _ = _compute_portfolio_heat(100_000)
        assert heat == 0.9


# ---------------------------------------------------------------------------
# TestSizeEquityTrade
# ---------------------------------------------------------------------------

class TestSizeEquityTrade:
    def _call(self, monkeypatch, symbol="INFY", direction="LONG",
              entry=1540.0, stoploss=1490.0, capital=100_000,
              risk_percent=1.0, target=None,
              heat_trades=None, port_score=30, port_rating="LOW"):
        monkeypatch.setattr(sizer_engine, "_get_open_trades",
                            lambda: _no_trades() if heat_trades is None else _trades_with(*heat_trades))
        monkeypatch.setattr(sizer_engine, "_get_portfolio_risk_report",
                            lambda: _port_report(port_score, port_rating))
        return sizer_engine.size_equity_trade(symbol, direction, entry, stoploss,
                                               capital, risk_percent, target)

    def test_basic_long_quantity(self, monkeypatch):
        # risk = 1000, distance = 50 → qty = 20
        result = self._call(monkeypatch, entry=1540.0, stoploss=1490.0,
                            capital=100_000, risk_percent=1.0)
        assert result["quantity"] == 20

    def test_basic_short_quantity(self, monkeypatch):
        # risk = 1000, distance = 50 → qty = 20
        result = self._call(monkeypatch, direction="SHORT",
                            entry=1540.0, stoploss=1590.0)
        assert result["quantity"] == 20

    def test_capital_required(self, monkeypatch):
        result = self._call(monkeypatch, entry=1000.0, stoploss=950.0)
        # qty = floor(1000/50) = 20, capital = 20*1000 = 20000
        assert result["capital_required"] == 20_000.0

    def test_max_loss_equals_qty_times_distance(self, monkeypatch):
        result = self._call(monkeypatch, entry=1000.0, stoploss=950.0)
        qty = result["quantity"]
        assert result["max_loss"] == round(qty * 50.0, 2)

    def test_risk_amount_equals_max_loss(self, monkeypatch):
        result = self._call(monkeypatch)
        assert result["risk_amount"] == result["max_loss"]

    def test_risk_reward_when_target_provided(self, monkeypatch):
        # entry=1000, sl=950, target=1100 → distance=50, reward=100 → rr=2.0
        result = self._call(monkeypatch, entry=1000.0, stoploss=950.0, target=1100.0)
        assert result["risk_reward"] == 2.0

    def test_no_risk_reward_without_target(self, monkeypatch):
        result = self._call(monkeypatch)
        assert "risk_reward" not in result

    def test_quantity_floor_at_one(self, monkeypatch):
        # tiny capital: risk = 10, distance = 500 → floor(10/500) = 0 → floor 1
        result = self._call(monkeypatch, capital=1_000, risk_percent=1.0,
                            entry=1540.0, stoploss=1040.0)
        assert result["quantity"] == 1

    def test_portfolio_heat_elevated_reduces_size(self, monkeypatch):
        # one open trade giving 7.5% heat
        trade = _open_trade(entry_price=1000.0, stoploss=0.0, quantity=375)
        # heat = 1000*375*0.02/100000*100 = 7.5% (uses default since sl=None)
        trade["stoploss"] = None
        result = self._call(monkeypatch, entry=1000.0, stoploss=950.0,
                            capital=100_000, heat_trades=[trade])
        # base = floor(1000/50)=20, factor=0.75 → 15
        assert result["quantity"] == 15
        assert len(result["size_adjustments"]) >= 1

    def test_portfolio_heat_critical_reduces_size_more(self, monkeypatch):
        # force heat computation to return > 9%
        original_heat = sizer_engine._compute_portfolio_heat
        monkeypatch.setattr(sizer_engine, "_compute_portfolio_heat",
                            lambda capital: (9.5, []))
        monkeypatch.setattr(sizer_engine, "_get_portfolio_risk_report",
                            lambda: _port_report(30, "LOW"))
        result = sizer_engine.size_equity_trade("INFY", "LONG", 1000.0, 950.0, 100_000)
        # base=20, critical factor=0.50 → 10
        assert result["quantity"] == 10

    def test_portfolio_risk_high_stacks_with_heat(self, monkeypatch):
        monkeypatch.setattr(sizer_engine, "_compute_portfolio_heat",
                            lambda capital: (7.5, []))
        monkeypatch.setattr(sizer_engine, "_get_portfolio_risk_report",
                            lambda: _port_report(80, "HIGH"))
        result = sizer_engine.size_equity_trade("INFY", "LONG", 1000.0, 950.0, 100_000)
        # base=20, heat=0.75, port=0.75 → 20*0.75*0.75=11.25 → 11
        assert result["quantity"] == 11

    def test_portfolio_risk_report_failure_no_crash(self, monkeypatch):
        monkeypatch.setattr(sizer_engine, "_get_open_trades", lambda: _no_trades())
        monkeypatch.setattr(sizer_engine, "_get_portfolio_risk_report",
                            lambda: (_ for _ in ()).throw(RuntimeError("auth required")))
        result = sizer_engine.size_equity_trade("INFY", "LONG", 1000.0, 950.0, 100_000)
        assert "error" not in result
        assert result["quantity"] >= 1

    def test_log_trade_params_present(self, monkeypatch):
        _setup_no_portfolio(monkeypatch)
        result = sizer_engine.size_equity_trade("INFY", "LONG", 1000.0, 950.0, 100_000)
        assert result["log_trade_params"] is not None

    def test_log_trade_params_keys(self, monkeypatch):
        _setup_no_portfolio(monkeypatch)
        result = sizer_engine.size_equity_trade("INFY", "LONG", 1000.0, 950.0,
                                                 100_000, target=1100.0)
        lp = result["log_trade_params"]
        for key in ("symbol", "direction", "entry_price", "quantity", "stoploss",
                    "risk_amount", "capital_at_risk", "portfolio_heat_at_entry"):
            assert key in lp, f"missing log_trade_params key: {key}"

    def test_log_trade_params_has_target_when_provided(self, monkeypatch):
        _setup_no_portfolio(monkeypatch)
        result = sizer_engine.size_equity_trade("INFY", "LONG", 1000.0, 950.0,
                                                 100_000, target=1100.0)
        assert result["log_trade_params"]["target"] == 1100.0

    def test_log_trade_params_no_target_when_omitted(self, monkeypatch):
        _setup_no_portfolio(monkeypatch)
        result = sizer_engine.size_equity_trade("INFY", "LONG", 1000.0, 950.0)
        assert "target" not in result["log_trade_params"]

    def test_stoploss_above_entry_long_returns_error(self, monkeypatch):
        _setup_no_portfolio(monkeypatch)
        result = sizer_engine.size_equity_trade("INFY", "LONG", 1000.0, 1050.0)
        assert "error" in result

    def test_stoploss_below_entry_short_returns_error(self, monkeypatch):
        _setup_no_portfolio(monkeypatch)
        result = sizer_engine.size_equity_trade("INFY", "SHORT", 1000.0, 950.0)
        assert "error" in result

    def test_invalid_direction_returns_error(self, monkeypatch):
        _setup_no_portfolio(monkeypatch)
        result = sizer_engine.size_equity_trade("INFY", "SIDEWAYS", 1000.0, 950.0)
        assert "error" in result

    def test_symbol_uppercased(self, monkeypatch):
        _setup_no_portfolio(monkeypatch)
        result = sizer_engine.size_equity_trade("infy", "LONG", 1000.0, 950.0)
        assert result["symbol"] == "INFY"

    def test_method_fixed_risk(self, monkeypatch):
        _setup_no_portfolio(monkeypatch)
        result = sizer_engine.size_equity_trade("INFY", "LONG", 1000.0, 950.0)
        assert result["method"] == "FIXED_RISK"

    def test_all_required_keys_present(self, monkeypatch):
        _setup_no_portfolio(monkeypatch)
        result = sizer_engine.size_equity_trade("INFY", "LONG", 1000.0, 950.0)
        for key in ("symbol", "direction", "entry", "stoploss", "target", "quantity",
                    "capital_required", "risk_amount", "capital_at_risk_pct", "max_loss",
                    "portfolio_heat_pct", "portfolio_heat_after_pct", "portfolio_risk_rating",
                    "size_adjustments", "cautions", "method", "log_trade_params"):
            assert key in result, f"missing key: {key}"

    def test_portfolio_heat_after_accounts_for_new_trade(self, monkeypatch):
        _setup_no_portfolio(monkeypatch)
        result = sizer_engine.size_equity_trade("INFY", "LONG", 1000.0, 950.0)
        # heat before = 0, heat after = capital_at_risk_pct
        assert result["portfolio_heat_after_pct"] == pytest.approx(
            result["capital_at_risk_pct"], abs=0.01
        )


# ---------------------------------------------------------------------------
# TestSizeOptionsTrade
# ---------------------------------------------------------------------------

class TestSizeOptionsTrade:
    def _call(self, monkeypatch, symbol="NIFTY", direction="LONG",
              premium=120.0, stoploss_premium=60.0, lot_size=50,
              capital=100_000, risk_percent=1.0):
        monkeypatch.setattr(sizer_engine, "_get_open_trades", lambda: _no_trades())
        monkeypatch.setattr(sizer_engine, "_get_portfolio_risk_report",
                            lambda: _port_report(30, "LOW"))
        return sizer_engine.size_options_trade(
            symbol, direction, premium, stoploss_premium, lot_size, capital, risk_percent
        )

    def test_basic_lots(self, monkeypatch):
        # risk=1000, lot_risk=60*50=3000 → lots=floor(1000/3000)=0 → floor 1
        result = self._call(monkeypatch)
        assert result["lots"] == 1

    def test_lots_with_larger_capital(self, monkeypatch):
        # risk=10000, lot_risk=60*50=3000 → lots=floor(10000/3000)=3
        monkeypatch.setattr(sizer_engine, "_get_open_trades", lambda: _no_trades())
        monkeypatch.setattr(sizer_engine, "_get_portfolio_risk_report",
                            lambda: _port_report(30, "LOW"))
        result = sizer_engine.size_options_trade("NIFTY", "LONG", 120.0, 60.0,
                                                  50, 1_000_000, 1.0)
        assert result["lots"] == 3

    def test_quantity_equals_lots_times_lot_size(self, monkeypatch):
        result = self._call(monkeypatch)
        assert result["quantity"] == result["lots"] * result["lot_size"]

    def test_capital_required(self, monkeypatch):
        result = self._call(monkeypatch)
        assert result["capital_required"] == round(result["lots"] * 50 * 120.0, 2)

    def test_max_loss(self, monkeypatch):
        # lots=1, lot_size=50, premium_distance=60 → max_loss=3000
        result = self._call(monkeypatch)
        assert result["max_loss"] == round(result["lots"] * 50 * 60.0, 2)

    def test_lots_floor_at_one(self, monkeypatch):
        # tiny capital
        monkeypatch.setattr(sizer_engine, "_get_open_trades", lambda: _no_trades())
        monkeypatch.setattr(sizer_engine, "_get_portfolio_risk_report",
                            lambda: _port_report(30, "LOW"))
        result = sizer_engine.size_options_trade("NIFTY", "LONG", 120.0, 60.0,
                                                  50, 100, 1.0)
        assert result["lots"] == 1

    def test_invalid_stoploss_premium_returns_error(self, monkeypatch):
        monkeypatch.setattr(sizer_engine, "_get_open_trades", lambda: _no_trades())
        monkeypatch.setattr(sizer_engine, "_get_portfolio_risk_report",
                            lambda: _port_report())
        result = sizer_engine.size_options_trade("NIFTY", "LONG", 120.0, 130.0, 50)
        assert "error" in result

    def test_zero_premium_distance_returns_error(self, monkeypatch):
        monkeypatch.setattr(sizer_engine, "_get_open_trades", lambda: _no_trades())
        monkeypatch.setattr(sizer_engine, "_get_portfolio_risk_report",
                            lambda: _port_report())
        result = sizer_engine.size_options_trade("NIFTY", "LONG", 120.0, 120.0, 50)
        assert "error" in result

    def test_caution_when_options_risk_exceeds_threshold(self, monkeypatch):
        # large premium, small capital → capital_at_risk > 5%
        monkeypatch.setattr(sizer_engine, "_get_open_trades", lambda: _no_trades())
        monkeypatch.setattr(sizer_engine, "_get_portfolio_risk_report",
                            lambda: _port_report())
        result = sizer_engine.size_options_trade("NIFTY", "LONG", 500.0, 100.0,
                                                  50, 10_000, 50.0)
        assert any("threshold" in c for c in result["cautions"])

    def test_log_trade_params_trade_type_options(self, monkeypatch):
        result = self._call(monkeypatch)
        assert result["log_trade_params"]["trade_type"] == "OPTIONS"

    def test_log_trade_params_entry_price_is_premium(self, monkeypatch):
        result = self._call(monkeypatch)
        assert result["log_trade_params"]["entry_price"] == 120.0

    def test_log_trade_params_stoploss_is_stoploss_premium(self, monkeypatch):
        result = self._call(monkeypatch)
        assert result["log_trade_params"]["stoploss"] == 60.0

    def test_log_trade_params_has_sizing_fields(self, monkeypatch):
        result = self._call(monkeypatch)
        lp = result["log_trade_params"]
        assert "risk_amount" in lp
        assert "capital_at_risk" in lp
        assert "portfolio_heat_at_entry" in lp

    def test_portfolio_heat_reduces_lots(self, monkeypatch):
        monkeypatch.setattr(sizer_engine, "_compute_portfolio_heat",
                            lambda capital: (7.5, []))
        monkeypatch.setattr(sizer_engine, "_get_portfolio_risk_report",
                            lambda: _port_report(30, "LOW"))
        # large capital so base_lots > 1
        result = sizer_engine.size_options_trade("NIFTY", "LONG", 120.0, 60.0,
                                                  50, 1_000_000, 1.0)
        # base = 3, factor = 0.75 → 2
        assert result["lots"] == 2

    def test_method_fixed_risk(self, monkeypatch):
        result = self._call(monkeypatch)
        assert result["method"] == "FIXED_RISK"

    def test_all_required_keys_present(self, monkeypatch):
        result = self._call(monkeypatch)
        for key in ("symbol", "direction", "premium", "stoploss_premium", "lot_size",
                    "lots", "quantity", "capital_required", "risk_amount",
                    "capital_at_risk_pct", "max_loss", "portfolio_heat_pct",
                    "portfolio_heat_after_pct", "portfolio_risk_rating",
                    "size_adjustments", "cautions", "method", "log_trade_params"):
            assert key in result, f"missing key: {key}"


# ---------------------------------------------------------------------------
# TestSizeFromRecommendation
# ---------------------------------------------------------------------------

class TestSizeFromRecommendation:
    def _setup(self, monkeypatch, rec=None, heat_pct=0.0, port_score=30, port_rating="LOW"):
        if rec is None:
            rec = _recommendation()
        monkeypatch.setattr(sizer_engine, "_recommend_trade",
                            lambda symbol, capital, risk_percent: rec)
        monkeypatch.setattr(sizer_engine, "_compute_portfolio_heat",
                            lambda capital: (heat_pct, []))
        monkeypatch.setattr(sizer_engine, "_get_portfolio_risk_report",
                            lambda: _port_report(port_score, port_rating))

    def test_enter_returns_full_sizing(self, monkeypatch):
        self._setup(monkeypatch)
        result = sizer_engine.size_from_recommendation("INFY")
        assert result["recommendation"] == "ENTER"
        assert result["quantity"] is not None
        assert result["capital_required"] is not None

    def test_avoid_nulls_sizing(self, monkeypatch):
        rec = _recommendation(recommendation="AVOID", trade_allowed=False,
                               cautions=["Extreme event risk"])
        self._setup(monkeypatch, rec=rec)
        result = sizer_engine.size_from_recommendation("INFY")
        assert result["quantity"] is None
        assert result["capital_required"] is None
        assert result["log_trade_params"] is None

    def test_avoid_caution_appended(self, monkeypatch):
        rec = _recommendation(recommendation="AVOID", trade_allowed=False)
        self._setup(monkeypatch, rec=rec)
        result = sizer_engine.size_from_recommendation("INFY")
        assert any("no sizing" in c.lower() for c in result["cautions"])

    def test_wait_still_sized(self, monkeypatch):
        rec = _recommendation(recommendation="WAIT", trade_allowed=True,
                               cautions=["Event risk HIGH"])
        self._setup(monkeypatch, rec=rec)
        result = sizer_engine.size_from_recommendation("INFY")
        assert result["quantity"] is not None
        assert result["log_trade_params"] is not None

    def test_recommendation_cautions_forwarded(self, monkeypatch):
        rec = _recommendation(cautions=["Event risk HIGH (65/100)"])
        self._setup(monkeypatch, rec=rec)
        result = sizer_engine.size_from_recommendation("INFY")
        assert any("Event risk" in c for c in result["cautions"])

    def test_phase13_position_size_used_as_base(self, monkeypatch):
        # Phase 13 returned position_size=6 (already adjusted)
        # Heat is 0 → no additional factor → quantity = 6
        rec = _recommendation(position_size=6)
        self._setup(monkeypatch, rec=rec, heat_pct=0.0)
        result = sizer_engine.size_from_recommendation("INFY")
        assert result["quantity"] == 6

    def test_portfolio_heat_factor_applied_on_top(self, monkeypatch):
        # base=6 from Phase 13, heat ELEVATED → * 0.75 = 4.5 → int(round(4.5)) = 4
        # (Python 3 banker's rounding: round(4.5) == 4)
        rec = _recommendation(position_size=6)
        self._setup(monkeypatch, rec=rec, heat_pct=7.5)
        result = sizer_engine.size_from_recommendation("INFY")
        assert result["quantity"] == 4

    def test_max_loss_computed_from_quantity_and_distance(self, monkeypatch):
        # entry=1540, sl=1490 → distance=50, qty=6 → max_loss=300
        rec = _recommendation(entry=1540.0, stoploss=1490.0, position_size=6)
        self._setup(monkeypatch, rec=rec)
        result = sizer_engine.size_from_recommendation("INFY")
        qty = result["quantity"]
        assert result["max_loss"] == round(qty * 50.0, 2)

    def test_capital_required_computed(self, monkeypatch):
        rec = _recommendation(entry=1540.0, stoploss=1490.0, position_size=6)
        self._setup(monkeypatch, rec=rec)
        result = sizer_engine.size_from_recommendation("INFY")
        qty = result["quantity"]
        assert result["capital_required"] == round(qty * 1540.0, 2)

    def test_log_trade_params_null_on_avoid(self, monkeypatch):
        rec = _recommendation(recommendation="AVOID", trade_allowed=False)
        self._setup(monkeypatch, rec=rec)
        result = sizer_engine.size_from_recommendation("INFY")
        assert result["log_trade_params"] is None

    def test_log_trade_params_has_sizing_fields(self, monkeypatch):
        self._setup(monkeypatch)
        result = sizer_engine.size_from_recommendation("INFY")
        lp = result["log_trade_params"]
        assert lp is not None
        assert "risk_amount" in lp
        assert "capital_at_risk" in lp
        assert "portfolio_heat_at_entry" in lp

    def test_context_keys_forwarded(self, monkeypatch):
        self._setup(monkeypatch)
        result = sizer_engine.size_from_recommendation("INFY")
        for key in ("signal", "regime", "strategy", "trade_quality",
                    "event_risk_score", "event_risk_rating",
                    "vix", "vix_caution", "duplicate_exposure"):
            assert key in result, f"missing context key: {key}"

    def test_recommend_trade_error_propagated(self, monkeypatch):
        monkeypatch.setattr(sizer_engine, "_recommend_trade",
                            lambda symbol, capital, risk_percent: {"error": "data unavailable"})
        monkeypatch.setattr(sizer_engine, "_compute_portfolio_heat",
                            lambda capital: (0.0, []))
        monkeypatch.setattr(sizer_engine, "_get_portfolio_risk_report",
                            lambda: _port_report())
        result = sizer_engine.size_from_recommendation("INFY")
        assert "error" in result

    def test_recommend_trade_exception_caught(self, monkeypatch):
        monkeypatch.setattr(sizer_engine, "_recommend_trade",
                            lambda symbol, capital, risk_percent: (_ for _ in ()).throw(RuntimeError("boom")))
        monkeypatch.setattr(sizer_engine, "_compute_portfolio_heat",
                            lambda capital: (0.0, []))
        monkeypatch.setattr(sizer_engine, "_get_portfolio_risk_report",
                            lambda: _port_report())
        result = sizer_engine.size_from_recommendation("INFY")
        assert "error" in result

    def test_symbol_uppercased(self, monkeypatch):
        self._setup(monkeypatch)
        result = sizer_engine.size_from_recommendation("infy")
        assert result["symbol"] == "INFY"

    def test_all_required_keys_present_enter(self, monkeypatch):
        self._setup(monkeypatch)
        result = sizer_engine.size_from_recommendation("INFY")
        for key in ("symbol", "recommendation", "trade_allowed", "direction",
                    "signal", "regime", "entry", "stoploss", "target", "risk_reward",
                    "strategy", "trade_quality", "event_risk_score", "event_risk_rating",
                    "vix", "vix_caution", "duplicate_exposure",
                    "quantity", "capital_required", "risk_amount", "capital_at_risk_pct",
                    "max_loss", "portfolio_heat_pct", "portfolio_heat_after_pct",
                    "portfolio_risk_rating", "size_adjustments", "cautions",
                    "method", "log_trade_params"):
            assert key in result, f"missing key: {key}"

    def test_all_required_keys_present_avoid(self, monkeypatch):
        rec = _recommendation(recommendation="AVOID", trade_allowed=False)
        self._setup(monkeypatch, rec=rec)
        result = sizer_engine.size_from_recommendation("INFY")
        for key in ("symbol", "recommendation", "trade_allowed", "direction",
                    "quantity", "capital_required", "risk_amount", "log_trade_params",
                    "cautions", "size_adjustments"):
            assert key in result, f"missing key: {key}"

    def test_portfolio_heat_at_entry_in_log_params(self, monkeypatch):
        self._setup(monkeypatch, heat_pct=2.5)
        result = sizer_engine.size_from_recommendation("INFY")
        lp = result["log_trade_params"]
        assert lp["portfolio_heat_at_entry"] == 2.5

    def test_method_fixed_risk(self, monkeypatch):
        self._setup(monkeypatch)
        result = sizer_engine.size_from_recommendation("INFY")
        assert result["method"] == "FIXED_RISK"

    def test_method_none_on_avoid(self, monkeypatch):
        rec = _recommendation(recommendation="AVOID", trade_allowed=False)
        self._setup(monkeypatch, rec=rec)
        result = sizer_engine.size_from_recommendation("INFY")
        assert result["method"] is None


# ---------------------------------------------------------------------------
# TestSchemaMigration
# ---------------------------------------------------------------------------

class TestSchemaMigration:
    """Verify schema v1→v2 migration adds the three new columns."""

    def _make_v1_conn(self):
        """Create an in-memory DB with the real Phase 12 v1 schema (no sizing columns)."""
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE schema_version (version INTEGER NOT NULL, applied TEXT NOT NULL)
        """)
        # Real Phase 12 schema — all columns EXCEPT risk_amount, capital_at_risk,
        # portfolio_heat_at_entry (those are the v2 additions under test)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id                TEXT    PRIMARY KEY,
                symbol            TEXT    NOT NULL,
                trade_type        TEXT    NOT NULL DEFAULT 'EQUITY',
                direction         TEXT    NOT NULL,
                strategy          TEXT,
                entry_price       REAL    NOT NULL,
                quantity          INTEGER,
                entry_date        TEXT    NOT NULL,
                entry_time        TEXT    NOT NULL,
                rationale         TEXT,
                stoploss          REAL,
                target            REAL,
                risk_reward       REAL,
                regime            TEXT,
                signal            TEXT,
                risk_score        INTEGER,
                analysis_snapshot TEXT,
                created_by        TEXT    NOT NULL DEFAULT 'MANUAL',
                status            TEXT    NOT NULL DEFAULT 'OPEN',
                exit_price        REAL,
                exit_date         TEXT,
                exit_time         TEXT,
                exit_reason       TEXT,
                pnl               REAL,
                pnl_percent       REAL,
                holding_days      INTEGER,
                tags              TEXT,
                notes             TEXT,
                created_at        TEXT    NOT NULL,
                updated_at        TEXT    NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_entry_date ON trades(entry_date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_trade_type ON trades(trade_type)")
        conn.execute("INSERT INTO schema_version VALUES (1, '2026-01-01T00:00:00')")
        conn.commit()
        return conn

    def test_migration_adds_risk_amount(self):
        import src.journal.db as journal_db
        conn = self._make_v1_conn()
        journal_db._init_schema(conn)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(trades)").fetchall()}
        assert "risk_amount" in cols

    def test_migration_adds_capital_at_risk(self):
        import src.journal.db as journal_db
        conn = self._make_v1_conn()
        journal_db._init_schema(conn)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(trades)").fetchall()}
        assert "capital_at_risk" in cols

    def test_migration_adds_portfolio_heat_at_entry(self):
        import src.journal.db as journal_db
        conn = self._make_v1_conn()
        journal_db._init_schema(conn)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(trades)").fetchall()}
        assert "portfolio_heat_at_entry" in cols

    def test_migration_updates_schema_version(self):
        import src.journal.db as journal_db
        conn = self._make_v1_conn()
        journal_db._init_schema(conn)
        version = conn.execute("SELECT version FROM schema_version").fetchone()[0]
        assert version == 2

    def test_migration_idempotent(self):
        """Running _init_schema twice on a v2 db must not raise."""
        import src.journal.db as journal_db
        conn = self._make_v1_conn()
        journal_db._init_schema(conn)
        journal_db._init_schema(conn)  # second call — must not crash
        version = conn.execute("SELECT version FROM schema_version").fetchone()[0]
        assert version == 2

    def test_fresh_install_starts_at_v2(self):
        import src.journal.db as journal_db
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        journal_db._init_schema(conn)
        version = conn.execute("SELECT version FROM schema_version").fetchone()[0]
        assert version == 2

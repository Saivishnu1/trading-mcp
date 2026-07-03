"""Regression tests for Phase 14 — Position Sizing Engine.

PS-1  quantity / lots always >= 1 (floor at one, never zero)
PS-2  max_loss = quantity × stoploss_distance exactly
PS-3  size_from_recommendation preserves all Phase 13 context keys
PS-4  portfolio heat handles missing stoploss gracefully (no crash)
PS-5  log_trade_params keys are valid log_trade() params; None (not {}) on AVOID
"""
from __future__ import annotations

import inspect

import pytest
import src.sizer.engine as sizer_engine
from src.sizer.engine import _apply_size_factors
from src.journal.service import log_trade as _log_trade


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _no_trades():
    return {"count": 0, "trades": []}


def _port_low():
    return {"portfolio_risk_score": 30, "rating": "LOW"}


def _recommendation(**overrides):
    base = {
        "symbol": "INFY",
        "recommendation": "ENTER",
        "trade_allowed": True,
        "direction": "LONG",
        "signal": "BUY",
        "regime": "BULL_TREND",
        "entry": 1540.0,
        "stoploss": 1490.0,
        "target": 1640.0,
        "risk_reward": 2.0,
        "position_size": 8,
        "strategy": "Bull Call Spread",
        "trade_quality": "HIGH_QUALITY",
        "event_risk_score": 35,
        "event_risk_rating": "LOW",
        "vix": 14.2,
        "vix_caution": "LOW",
        "duplicate_exposure": False,
        "cautions": [],
        "reasons": ["BULL_TREND regime with BUY signal"],
        "risk_adjustments": [],
    }
    base.update(overrides)
    return base


def _setup_clean(monkeypatch):
    monkeypatch.setattr(sizer_engine, "_get_open_trades", lambda: _no_trades())
    monkeypatch.setattr(sizer_engine, "_get_portfolio_risk_report", lambda: _port_low())
    monkeypatch.setattr(sizer_engine, "_compute_portfolio_heat", lambda capital: (0.0, []))


# ---------------------------------------------------------------------------
# PS-1: quantity / lots always >= 1
# ---------------------------------------------------------------------------

class TestPS1QuantityFloor:
    def test_options_tiny_capital_lots_at_least_one(self, monkeypatch):
        _setup_clean(monkeypatch)
        result = sizer_engine.size_options_trade(
            "NIFTY", "LONG", 120.0, 60.0, 50, capital=100, risk_percent=1.0
        )
        assert result["lots"] >= 1

    def test_options_quantity_at_least_lot_size(self, monkeypatch):
        _setup_clean(monkeypatch)
        result = sizer_engine.size_options_trade(
            "NIFTY", "LONG", 120.0, 60.0, 50, capital=100, risk_percent=1.0
        )
        assert result["quantity"] >= result["lot_size"]

    def test_apply_size_factors_never_zero(self):
        # extreme stacking
        result = _apply_size_factors(1, [0.50, 0.50, 0.50])
        assert result >= 1

    def test_from_recommendation_quantity_at_least_one(self, monkeypatch):
        rec = _recommendation(position_size=1)
        monkeypatch.setattr(sizer_engine, "_recommend_trade",
                            lambda symbol, capital, risk_percent: rec)
        monkeypatch.setattr(sizer_engine, "_compute_portfolio_heat",
                            lambda capital: (9.5, []))  # critical factor 0.50
        monkeypatch.setattr(sizer_engine, "_get_portfolio_risk_report",
                            lambda: {"portfolio_risk_score": 92, "rating": "EXTREME"})
        result = sizer_engine.size_from_recommendation("INFY")
        assert result["quantity"] is not None
        assert result["quantity"] >= 1


# ---------------------------------------------------------------------------
# PS-2: max_loss = quantity × stoploss_distance exactly
# ---------------------------------------------------------------------------

class TestPS2MaxLossFormula:
    def test_options_max_loss(self, monkeypatch):
        _setup_clean(monkeypatch)
        premium, sl_premium, lot_size = 120.0, 60.0, 50
        result = sizer_engine.size_options_trade("NIFTY", "LONG", premium,
                                                  sl_premium, lot_size)
        lots = result["lots"]
        expected = round(lots * lot_size * (premium - sl_premium), 2)
        assert result["max_loss"] == expected

    def test_risk_amount_equals_max_loss_options(self, monkeypatch):
        _setup_clean(monkeypatch)
        result = sizer_engine.size_options_trade("NIFTY", "LONG", 120.0, 60.0, 50)
        assert result["risk_amount"] == result["max_loss"]

    def test_from_recommendation_max_loss_matches_formula(self, monkeypatch):
        rec = _recommendation(entry=1540.0, stoploss=1490.0, position_size=6)
        monkeypatch.setattr(sizer_engine, "_recommend_trade",
                            lambda symbol, capital, risk_percent: rec)
        monkeypatch.setattr(sizer_engine, "_compute_portfolio_heat",
                            lambda capital: (0.0, []))
        monkeypatch.setattr(sizer_engine, "_get_portfolio_risk_report",
                            lambda: _port_low())
        result = sizer_engine.size_from_recommendation("INFY")
        qty = result["quantity"]
        assert result["max_loss"] == round(qty * 50.0, 2)


# ---------------------------------------------------------------------------
# PS-3: size_from_recommendation preserves all Phase 13 context keys
# ---------------------------------------------------------------------------

class TestPS3RecommendationContextPreserved:
    PHASE13_KEYS = (
        "signal", "regime", "strategy", "trade_quality",
        "event_risk_score", "event_risk_rating",
        "vix", "vix_caution", "duplicate_exposure",
    )

    def _call_enter(self, monkeypatch):
        monkeypatch.setattr(sizer_engine, "_recommend_trade",
                            lambda symbol, capital, risk_percent: _recommendation())
        monkeypatch.setattr(sizer_engine, "_compute_portfolio_heat",
                            lambda capital: (0.0, []))
        monkeypatch.setattr(sizer_engine, "_get_portfolio_risk_report",
                            lambda: _port_low())
        return sizer_engine.size_from_recommendation("INFY")

    def test_all_phase13_keys_in_enter_response(self, monkeypatch):
        result = self._call_enter(monkeypatch)
        for key in self.PHASE13_KEYS:
            assert key in result, f"missing Phase 13 key: {key}"

    def test_phase13_values_unchanged(self, monkeypatch):
        result = self._call_enter(monkeypatch)
        rec = _recommendation()
        assert result["signal"] == rec["signal"]
        assert result["regime"] == rec["regime"]
        assert result["event_risk_score"] == rec["event_risk_score"]
        assert result["vix"] == rec["vix"]
        assert result["duplicate_exposure"] == rec["duplicate_exposure"]

    def test_phase13_keys_present_on_avoid(self, monkeypatch):
        rec = _recommendation(recommendation="AVOID", trade_allowed=False)
        monkeypatch.setattr(sizer_engine, "_recommend_trade",
                            lambda symbol, capital, risk_percent: rec)
        monkeypatch.setattr(sizer_engine, "_compute_portfolio_heat",
                            lambda capital: (0.0, []))
        monkeypatch.setattr(sizer_engine, "_get_portfolio_risk_report",
                            lambda: _port_low())
        result = sizer_engine.size_from_recommendation("INFY")
        for key in self.PHASE13_KEYS:
            assert key in result, f"missing Phase 13 key on AVOID: {key}"

    def test_heat_adjustment_does_not_drop_context_keys(self, monkeypatch):
        monkeypatch.setattr(sizer_engine, "_recommend_trade",
                            lambda symbol, capital, risk_percent: _recommendation())
        monkeypatch.setattr(sizer_engine, "_compute_portfolio_heat",
                            lambda capital: (7.5, []))
        monkeypatch.setattr(sizer_engine, "_get_portfolio_risk_report",
                            lambda: _port_low())
        result = sizer_engine.size_from_recommendation("INFY")
        for key in self.PHASE13_KEYS:
            assert key in result, f"key dropped after heat adjustment: {key}"


# ---------------------------------------------------------------------------
# PS-4: portfolio heat handles missing stoploss gracefully
# ---------------------------------------------------------------------------

class TestPS4PortfolioHeatMissingStoploss:
    def test_open_trade_without_stoploss_no_crash(self, monkeypatch):
        trade = {
            "trade_id": "TRD-aaaa0001",
            "symbol": "INFY",
            "direction": "LONG",
            "entry_price": 1540.0,
            "stoploss": None,
            "quantity": 10,
        }
        monkeypatch.setattr(sizer_engine, "_get_open_trades",
                            lambda: {"count": 1, "trades": [trade]})
        heat, cautions = sizer_engine._compute_portfolio_heat(100_000)
        assert isinstance(heat, float)
        assert heat >= 0.0

    def test_all_trades_missing_stoploss_no_crash(self, monkeypatch):
        trades = [
            {"trade_id": f"TRD-{i:08d}", "symbol": "X", "direction": "LONG",
             "entry_price": 1000.0, "stoploss": None, "quantity": 5}
            for i in range(5)
        ]
        monkeypatch.setattr(sizer_engine, "_get_open_trades",
                            lambda: {"count": 5, "trades": trades})
        heat, cautions = sizer_engine._compute_portfolio_heat(100_000)
        assert isinstance(heat, float)
        assert cautions == []

    def test_missing_stoploss_uses_default_2pct(self, monkeypatch):
        trade = {
            "trade_id": "TRD-aaaa0001",
            "symbol": "INFY",
            "direction": "LONG",
            "entry_price": 1000.0,
            "stoploss": None,
            "quantity": 10,
        }
        monkeypatch.setattr(sizer_engine, "_get_open_trades",
                            lambda: {"count": 1, "trades": [trade]})
        # expected: 1000 * 10 * 0.02 / 100000 * 100 = 0.2%
        heat, _ = sizer_engine._compute_portfolio_heat(100_000)
        assert heat == pytest.approx(0.2, abs=0.01)

    def test_get_open_trades_error_returns_zero_heat_with_caution(self, monkeypatch):
        monkeypatch.setattr(sizer_engine, "_get_open_trades",
                            lambda: {"error": "connection failed"})
        heat, cautions = sizer_engine._compute_portfolio_heat(100_000)
        assert heat == 0.0
        assert len(cautions) == 1
        assert "connection failed" in cautions[0]


# ---------------------------------------------------------------------------
# PS-5: log_trade_params validity
# ---------------------------------------------------------------------------

class TestPS5LogTradeParamsValidity:
    # These are the parameter names accepted by log_trade()
    VALID_LOG_TRADE_PARAMS = frozenset(inspect.signature(_log_trade).parameters.keys())

    def test_options_log_trade_params_keys_valid(self, monkeypatch):
        _setup_clean(monkeypatch)
        result = sizer_engine.size_options_trade("NIFTY", "LONG", 120.0, 60.0, 50)
        lp = result["log_trade_params"]
        for key in lp:
            assert key in self.VALID_LOG_TRADE_PARAMS, (
                f"log_trade_params key '{key}' is not a valid log_trade() parameter"
            )

    def test_from_recommendation_log_trade_params_keys_valid(self, monkeypatch):
        monkeypatch.setattr(sizer_engine, "_recommend_trade",
                            lambda symbol, capital, risk_percent: _recommendation())
        monkeypatch.setattr(sizer_engine, "_compute_portfolio_heat",
                            lambda capital: (0.0, []))
        monkeypatch.setattr(sizer_engine, "_get_portfolio_risk_report",
                            lambda: _port_low())
        result = sizer_engine.size_from_recommendation("INFY")
        lp = result["log_trade_params"]
        assert lp is not None
        for key in lp:
            assert key in self.VALID_LOG_TRADE_PARAMS, (
                f"log_trade_params key '{key}' is not a valid log_trade() parameter"
            )

    def test_log_trade_params_is_none_not_empty_dict_on_avoid(self, monkeypatch):
        rec = _recommendation(recommendation="AVOID", trade_allowed=False)
        monkeypatch.setattr(sizer_engine, "_recommend_trade",
                            lambda symbol, capital, risk_percent: rec)
        monkeypatch.setattr(sizer_engine, "_compute_portfolio_heat",
                            lambda capital: (0.0, []))
        monkeypatch.setattr(sizer_engine, "_get_portfolio_risk_report",
                            lambda: _port_low())
        result = sizer_engine.size_from_recommendation("INFY")
        assert result["log_trade_params"] is None
        assert result["log_trade_params"] != {}


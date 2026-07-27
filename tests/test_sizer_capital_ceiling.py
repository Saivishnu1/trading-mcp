"""Regression tests for Audit-C1 — capital ceiling on position sizing.

Finding: risk-based sizing (risk_budget / stoploss_distance) had no upper
bound tied to account size. A tight stoploss relative to entry price could
size a position whose notional value (quantity * price) exceeds the
account's entire stated capital, with capital_at_risk_pct (based on max_loss,
not notional) staying well under the 5% caution threshold — no warning, no
block.

CC-1  size_options_trade never returns a lot count whose notional exceeds capital
CC-2  size_equity_trade never returns a quantity whose notional exceeds capital
CC-3  size_from_recommendation clamps quantity to the capital ceiling too
CC-4  a capital_ceiling caution/adjustment is surfaced when clamping occurs
CC-5  calculate_position_size (regime.py) surfaces capital_required and flags when it exceeds capital
CC-6  no ceiling is applied (and no caution fires) when the risk-based size already fits
"""
from __future__ import annotations

import src.sizer.engine as sizer_engine
from src.analysis.regime import calculate_position_size


def _no_trades():
    return {"count": 0, "trades": []}


def _port_low():
    return {"portfolio_risk_score": 30, "rating": "LOW"}


def _setup_clean(monkeypatch):
    monkeypatch.setattr(sizer_engine, "_get_open_trades", lambda: _no_trades())
    monkeypatch.setattr(sizer_engine, "_get_portfolio_risk_report", lambda: _port_low())
    monkeypatch.setattr(sizer_engine, "_compute_portfolio_heat", lambda capital: (0.0, []))


class TestCC1OptionsCapitalCeiling:
    def test_tight_stop_does_not_exceed_capital(self, monkeypatch):
        _setup_clean(monkeypatch)
        # premium=120, stop=119 (premium_distance=1), lot_size=50, capital=100_000, risk=1%
        # risk_budget=1000, lot_risk=50, base_lots=20 -> capital_required = 20*50*120 = 120_000 (> capital)
        result = sizer_engine.size_options_trade(
            "NIFTY", "LONG", premium=120.0, stoploss_premium=119.0, lot_size=50,
            capital=100_000, risk_percent=1.0,
        )
        assert result["capital_required"] <= 100_000

    def test_ceiling_caution_present_when_clamped(self, monkeypatch):
        _setup_clean(monkeypatch)
        result = sizer_engine.size_options_trade(
            "NIFTY", "LONG", premium=120.0, stoploss_premium=119.0, lot_size=50,
            capital=100_000, risk_percent=1.0,
        )
        assert any("capital ceiling" in msg.lower() for msg in result["size_adjustments"])

    def test_lots_still_at_least_one(self, monkeypatch):
        _setup_clean(monkeypatch)
        result = sizer_engine.size_options_trade(
            "NIFTY", "LONG", premium=120.0, stoploss_premium=119.0, lot_size=50,
            capital=100_000, risk_percent=1.0,
        )
        assert result["lots"] >= 1


class TestCC2EquityCapitalCeiling:
    def test_tight_stop_does_not_exceed_capital(self, monkeypatch):
        _setup_clean(monkeypatch)
        # entry=100, stop=99.5 (distance=0.5), capital=100_000, risk=1%
        # risk_budget=1000, base_quantity=floor(1000/0.5)=2000 -> capital_required=200_000 (> capital)
        result = sizer_engine.size_equity_trade(
            "RELIANCE", "LONG", entry=100.0, stoploss=99.5,
            capital=100_000, risk_percent=1.0,
        )
        assert result["capital_required"] <= 100_000

    def test_quantity_still_at_least_one(self, monkeypatch):
        _setup_clean(monkeypatch)
        result = sizer_engine.size_equity_trade(
            "RELIANCE", "LONG", entry=100.0, stoploss=99.5,
            capital=100_000, risk_percent=1.0,
        )
        assert result["quantity"] >= 1

    def test_no_ceiling_note_when_size_fits(self, monkeypatch):
        _setup_clean(monkeypatch)
        # entry=100, stop=95 (distance=5), capital=100_000, risk=1% -> qty=200, capital_required=20_000 (fits)
        result = sizer_engine.size_equity_trade(
            "RELIANCE", "LONG", entry=100.0, stoploss=95.0,
            capital=100_000, risk_percent=1.0,
        )
        assert result["capital_required"] <= 100_000
        assert not any("capital ceiling" in msg.lower() for msg in result["size_adjustments"])


class TestCC3FromRecommendationCapitalCeiling:
    def _recommendation(self, **overrides):
        base = {
            "symbol": "INFY",
            "recommendation": "ENTER",
            "trade_allowed": True,
            "direction": "LONG",
            "signal": "BUY",
            "regime": "BULL_TREND",
            "entry": 1540.0,
            "stoploss": 1538.0,  # very tight stop relative to entry
            "target": 1640.0,
            "risk_reward": 2.0,
            "position_size": 500,  # base_position_size already computed upstream, unbounded
            "strategy": "Bull Call Spread",
            "trade_quality": "HIGH_QUALITY",
            "event_risk_score": 35,
            "event_risk_rating": "LOW",
            "vix": 14.2,
            "vix_caution": "LOW",
            "duplicate_exposure": False,
            "cautions": [],
            "reasons": ["BULL_TREND regime with BUY signal"],
        }
        base.update(overrides)
        return base

    def test_quantity_clamped_to_capital(self, monkeypatch):
        rec = self._recommendation()
        monkeypatch.setattr(sizer_engine, "_recommend_trade",
                             lambda symbol, capital, risk_percent: rec)
        _setup_clean(monkeypatch)
        result = sizer_engine.size_from_recommendation("INFY", capital=100_000)
        # 500 * 1540 = 770_000, far beyond 100_000 capital
        assert result["capital_required"] <= 100_000
        assert result["quantity"] < 500


class TestCC5RegimeCalculatePositionSize:
    def test_flags_when_capital_required_exceeds_capital(self):
        # entry=100, stoploss=99.5 (distance=0.5), capital=100_000, risk=1%
        # risk_amount=1000, position_size=2000, capital_required=200_000 (exceeds capital)
        r = calculate_position_size(capital=100_000, risk_percent=1.0, entry=100, stoploss=99.5)
        assert "capital_ceiling_caution" in r
        assert r["capital_capped_position_size"] * 100 <= 100_000

    def test_no_flag_when_size_fits_capital(self):
        r = calculate_position_size(capital=100_000, risk_percent=1.0, entry=100, stoploss=95)
        assert "capital_ceiling_caution" not in r
        assert r["capital_required"] <= 100_000

    def test_position_size_field_unchanged_for_backward_compat(self):
        # Existing test_analysis.py::TestCalculatePositionSize::test_basic expects
        # position_size == 200 for this input; ceiling must be additive, not mutate it.
        r = calculate_position_size(capital=100_000, risk_percent=1.0, entry=100, stoploss=95)
        assert r["position_size"] == 200.0

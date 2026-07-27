"""Regression tests for Audit-H1 — weekly/monthly regime conflict must
actually reduce position size, not just add a caution string.

Finding: recommend_trade()'s weekly-regime-conflict check (Phase 19) only
appended a string to `cautions`. Every other gate (event risk, VIX,
duplicate exposure) sets trade_allowed=False and/or appends a size_factor.
The regime-conflict path touched neither, so a WAIT-due-to-regime-conflict
recommendation still carried the full, undiminished position_size — and
downstream, size_from_recommendation only bypassed sizing when
trade_allowed was False or recommendation == "AVOID", so WAIT-with-cautions
proceeded to full-size sizing (see Audit-H1's sibling fix in
test_sizer_engine.py::test_wait_is_not_sized).

RTC-1  daily BUY + weekly BEAR_TREND -> position_size reduced (size_factor applied)
RTC-2  daily SELL + weekly BULL_TREND -> position_size reduced (short side too)
RTC-3  strong alignment (weekly confirms daily) -> no size reduction, no caution
RTC-4  no weekly regime data available -> no size reduction (graceful degradation, Phase 19 rule)
RTC-5  a risk_adjustments entry explains the weekly-conflict size cut
"""
from __future__ import annotations

import src.recommendations.engine as rec_engine


def _base_plan(**overrides):
    plan = {
        "signal": "BUY",
        "trade_allowed": True,
        "market_context": {"regime": "BULL_TREND"},
        "entry": 100.0,
        "stoploss": 95.0,
        "target": 115.0,
        "risk_reward": {"rr": 3.0},
        "position": {"position_size": 100},
        "strategy": {"recommended": "Bull Call Spread"},
        "trade_quality": "HIGH_QUALITY",
        "data_basis": {"staleness_days": 0, "last_candle_date": "2026-07-22"},
    }
    plan.update(overrides)
    return plan


def _no_open_trades():
    return {"trades": []}


def _setup_common(monkeypatch, plan=None, alignment=None):
    monkeypatch.setattr(rec_engine, "_get_open_trades", lambda symbol=None: _no_open_trades())
    monkeypatch.setattr(rec_engine, "_create_trade_plan",
                         lambda symbol, capital, risk_percent: plan or _base_plan())
    monkeypatch.setattr(rec_engine, "_get_event_risk", lambda symbol: {"error": "unavailable"})
    monkeypatch.setattr(rec_engine, "_get_india_vix", lambda: {"error": "unavailable"})
    monkeypatch.setattr(rec_engine, "_get_regime_alignment",
                         lambda symbol: alignment if alignment is not None else {"error": "unavailable"})


class TestRTC1LongVsBearishWeekly:
    def test_position_size_reduced(self, monkeypatch):
        alignment = {"weekly": {"regime": "BEAR_TREND"}, "alignment": "CONFLICT"}
        _setup_common(monkeypatch, alignment=alignment)
        result = rec_engine.recommend_trade("NIFTY")
        assert result["position_size"] < 100
        assert result["position_size"] == 50  # base 100 * 0.50 conflict factor

    def test_recommendation_is_wait_not_enter(self, monkeypatch):
        alignment = {"weekly": {"regime": "BEAR_TREND"}, "alignment": "CONFLICT"}
        _setup_common(monkeypatch, alignment=alignment)
        result = rec_engine.recommend_trade("NIFTY")
        assert result["recommendation"] == "WAIT"

    def test_neutral_bearish_weekly_also_reduces_size(self, monkeypatch):
        alignment = {"weekly": {"regime": "NEUTRAL_BEARISH"}, "alignment": "CONFLICT"}
        _setup_common(monkeypatch, alignment=alignment)
        result = rec_engine.recommend_trade("NIFTY")
        assert result["position_size"] == 50


class TestRTC2ShortVsBullishWeekly:
    def test_position_size_reduced_for_short(self, monkeypatch):
        plan = _base_plan(signal="SELL", market_context={"regime": "BEAR_TREND"})
        alignment = {"weekly": {"regime": "BULL_TREND"}, "alignment": "CONFLICT"}
        _setup_common(monkeypatch, plan=plan, alignment=alignment)
        result = rec_engine.recommend_trade("NIFTY")
        assert result["position_size"] == 50


class TestRTC3StrongAlignmentNoReduction:
    def test_no_size_reduction_when_weekly_confirms_daily(self, monkeypatch):
        alignment = {"weekly": {"regime": "BULL_TREND"}, "alignment": "STRONG"}
        _setup_common(monkeypatch, alignment=alignment)
        result = rec_engine.recommend_trade("NIFTY")
        assert result["position_size"] == 100
        assert not any("conflict" in c.lower() for c in result["cautions"])


class TestRTC4NoWeeklyDataGracefulDegradation:
    def test_no_size_reduction_when_alignment_unavailable(self, monkeypatch):
        _setup_common(monkeypatch, alignment={"error": "unavailable"})
        result = rec_engine.recommend_trade("NIFTY")
        assert result["position_size"] == 100
        assert result["weekly_regime"] is None


class TestRTC5RiskAdjustmentExplainsSizeCut:
    def test_risk_adjustments_mentions_weekly_conflict(self, monkeypatch):
        alignment = {"weekly": {"regime": "BEAR_TREND"}, "alignment": "CONFLICT"}
        _setup_common(monkeypatch, alignment=alignment)
        result = rec_engine.recommend_trade("NIFTY")
        assert any("weekly" in adj.lower() for adj in result["risk_adjustments"])

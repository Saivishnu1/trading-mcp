"""
Regression tests for reliability issues found during a live trading session
(2026-07-10):

1. oi_call_wall_break/oi_put_wall_break firing on every single-poll cross
   instead of a confirmed hold — covered in test_market_intelligence.py /
   test_monitor.py (Priority 1). This file covers Priorities 2-4.
2. Technical indicators (ADX/RSI/MACD/EMA) sourced from lagging EOD-adjusted
   yfinance candles even when Zerodha is authenticated.
3. Max-pain pinning risk during expiry week not surfaced proactively.
4. Trade-count/cost visibility missing entirely.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp.server.fastmcp import FastMCP as _FastMCP

from src import meta as _meta

# ---------------------------------------------------------------------------
# Priority 2 — Zerodha-derived indicators, yfinance as last-resort fallback
# ---------------------------------------------------------------------------


class TestTieredIndicatorSource:
    def test_load_candles_with_source_prefers_zerodha_over_yfinance(self):
        from src.tools import technicals

        zerodha_candles = [
            {"datetime": "2026-07-10", "open": 24100.0, "high": 24250.0, "low": 24050.0, "close": 24200.0, "volume": 0},
        ]
        with patch("src.tools.technicals.get_market") as mock_get_market:
            with patch(
                "src.chart_awareness.data_fetcher.fetch_candles",
                new=AsyncMock(return_value=(zerodha_candles, "zerodha")),
            ):
                candles, source = technicals._load_candles_with_source("NIFTY", 60)

        assert source == "zerodha"
        assert candles[0]["close"] == 24200.0
        # yfinance-only path must never even be consulted when the tiered
        # fetcher already returned candles.
        mock_get_market.return_value.get_historical.assert_not_called()

    def test_load_candles_with_source_falls_back_to_yahoo_when_tiered_exhausted(self):
        from src.tools import technicals

        yf_candles = [
            {"date": "2026-07-10", "open": 24100.0, "high": 24250.0, "low": 24050.0, "close": 24180.0, "volume": 0},
        ]
        with patch("src.tools.technicals.get_market") as mock_get_market:
            mock_get_market.return_value.get_historical.return_value = yf_candles
            with patch(
                "src.chart_awareness.data_fetcher.fetch_candles",
                new=AsyncMock(return_value=([], "none")),
            ):
                candles, source = technicals._load_candles_with_source("NIFTY", 60)

        assert source == "yahoo"
        assert candles[0]["close"] == 24180.0

    def test_load_closes_with_source_propagates_source_label(self):
        from src.tools import technicals

        zerodha_candles = [
            {"datetime": "2026-07-10", "open": 24100.0, "high": 24250.0, "low": 24050.0, "close": 24200.0, "volume": 0},
        ]
        with patch(
            "src.chart_awareness.data_fetcher.fetch_candles",
            new=AsyncMock(return_value=(zerodha_candles, "zerodha")),
        ):
            closes, highs, lows, source = technicals._load_closes_with_source("NIFTY", 60)

        assert source == "zerodha"
        assert closes == [24200.0]

    def test_load_closes_with_source_none_on_total_failure(self):
        from src.tools import technicals

        with patch("src.tools.technicals.get_market") as mock_get_market:
            mock_get_market.return_value.get_historical.return_value = []
            with patch(
                "src.chart_awareness.data_fetcher.fetch_candles",
                new=AsyncMock(return_value=([], "none")),
            ):
                closes, highs, lows, source = technicals._load_closes_with_source("NIFTY", 60)

        assert closes is None
        assert source == "none"


class TestIndicatorMetaSourceLabeling:
    def test_indicator_meta_default_preserves_yfinance_note(self):
        meta = _meta.indicator_meta({"rsi": 55.0}, symbol="NIFTY")
        assert meta["source"] == "yfinance"
        assert "yfinance" in meta["limitations"][0]

    def test_indicator_meta_zerodha_source_gets_broker_note(self):
        meta = _meta.indicator_meta({"rsi": 55.0}, symbol="NIFTY", source="zerodha")
        assert meta["source"] == "zerodha"
        assert "Zerodha" in meta["limitations"][0]
        assert "yfinance" not in meta["limitations"][0]

    def test_indicator_meta_zerodha_source_has_no_eod_warning_outside_hours(self):
        with patch("src.meta.is_market_hours", return_value=False):
            meta = _meta.indicator_meta({"rsi": 55.0}, symbol="NIFTY", source="zerodha")
        assert meta.get("warning") is None

    def test_indicator_meta_yfinance_source_still_warns_outside_hours(self):
        with patch("src.meta.is_market_hours", return_value=False):
            meta = _meta.indicator_meta({"rsi": 55.0}, symbol="NIFTY", source="yfinance")
        assert meta.get("warning")


class TestCalculateAtrSourceLabel:
    def test_calculate_atr_reports_zerodha_source_in_meta(self):
        from src.tools import technicals

        mcp = _FastMCP("test")
        technicals.register(mcp)
        tools = {t.name: t for t in mcp._tool_manager.list_tools()}

        zerodha_candles = [
            {"date": f"2026-07-{d:02d}", "open": 100.0, "high": 105.0, "low": 95.0, "close": 100.0 + d, "volume": 0}
            for d in range(1, 20)
        ]
        with patch(
            "src.tools.technicals._load_candles_with_source",
            return_value=(zerodha_candles, "zerodha"),
        ):
            result = tools["calculate_atr"].fn("NIFTY")

        assert result["meta"]["source"] == "zerodha"

    def test_calculate_atr_reports_yfinance_source_when_falling_back(self):
        from src.tools import technicals

        mcp = _FastMCP("test")
        technicals.register(mcp)
        tools = {t.name: t for t in mcp._tool_manager.list_tools()}

        yf_candles = [
            {"date": f"2026-07-{d:02d}", "open": 100.0, "high": 105.0, "low": 95.0, "close": 100.0 + d, "volume": 0}
            for d in range(1, 20)
        ]
        with patch(
            "src.tools.technicals._load_candles_with_source",
            return_value=(yf_candles, "yahoo"),
        ):
            result = tools["calculate_atr"].fn("NIFTY")

        assert result["meta"]["source"] == "yahoo"


class TestDashboardTechnicalsSourceLabel:
    def test_technicals_section_reports_data_source(self):
        from src.dashboard import service

        closes = [24000.0 + i for i in range(60)]
        highs = [c + 5 for c in closes]
        lows = [c - 5 for c in closes]
        with patch(
            "src.dashboard.service._load_closes_with_source",
            return_value=(closes, highs, lows, "zerodha"),
        ):
            tech, last_close = service._technicals_section("NIFTY")

        assert tech["data_source"] == "zerodha"
        assert last_close == closes[-1]

    def test_technicals_section_includes_ema200(self):
        from src.dashboard import service

        closes = [24000.0 + i for i in range(220)]
        highs = [c + 5 for c in closes]
        lows = [c - 5 for c in closes]
        with patch(
            "src.dashboard.service._load_closes_with_source",
            return_value=(closes, highs, lows, "zerodha"),
        ):
            tech, _ = service._technicals_section("NIFTY")

        assert "ema200" in tech

    def test_technicals_section_error_still_reports_data_source(self):
        from src.dashboard import service

        with patch(
            "src.dashboard.service._load_closes_with_source",
            return_value=(None, None, None, "none"),
        ):
            tech, last_close = service._technicals_section("NIFTY")

        assert tech["data_source"] == "none"
        assert "error" in tech
        assert last_close is None


# ---------------------------------------------------------------------------
# Priority 3 — max-pain pinning-risk flag during expiry week
# ---------------------------------------------------------------------------


class TestCheckPinningRisk:
    def test_active_when_within_threshold_during_expiry_week(self):
        from src.options import analytics

        result = analytics.check_pinning_risk(spot=24205.0, max_pain=24200.0, is_expiry_week=True, threshold_pct=0.5)
        assert result["active"] is True
        assert result["distance_points"] == 5.0

    def test_inactive_when_far_from_max_pain(self):
        from src.options import analytics

        result = analytics.check_pinning_risk(spot=24500.0, max_pain=24200.0, is_expiry_week=True, threshold_pct=0.5)
        assert result["active"] is False

    def test_inactive_outside_expiry_week_even_if_pinned(self):
        from src.options import analytics

        result = analytics.check_pinning_risk(spot=24205.0, max_pain=24200.0, is_expiry_week=False, threshold_pct=0.5)
        assert result["active"] is False

    def test_boundary_at_exactly_threshold_pct_is_active(self):
        from src.options import analytics

        spot = 24200.0
        max_pain = spot * (1 - 0.005)  # exactly 0.5% away
        result = analytics.check_pinning_risk(spot=spot, max_pain=max_pain, is_expiry_week=True, threshold_pct=0.5)
        assert result["active"] is True

    def test_missing_spot_or_max_pain_is_inactive(self):
        from src.options import analytics

        assert analytics.check_pinning_risk(None, 24200.0, True)["active"] is False
        assert analytics.check_pinning_risk(24200.0, None, True)["active"] is False


class TestMarketAwarenessPinningRisk:
    @pytest.mark.anyio
    async def test_pinning_risk_active_during_expiry_week_near_max_pain(self):
        from src.market_awareness.engine import MarketAwarenessEngine

        raw_data = {
            "chart": {}, "candlestick": {}, "chart_patterns": {},
            "options": {"spot": 24205.0, "max_pain": 24200.0, "walls": {}, "iv": {}, "oi_levels": {}},
            "global": {}, "vix": {}, "calendar": {
                "expiries": {"nifty": "2026-07-10"},
                "days_to_expiry": {"nifty": 0},
            },
        }
        with patch("src.market_awareness.engine.MarketAggregator") as mock_agg_cls, \
             patch("src.market_awareness.engine.detect_market_regime", return_value={}):
            mock_agg = MagicMock()
            mock_agg.collect = AsyncMock(return_value=raw_data)
            mock_agg_cls.return_value = mock_agg

            result = await MarketAwarenessEngine().analyze("NIFTY")

        assert result["calendar"]["is_expiry_week"] is True
        assert result["calendar"]["pinning_risk"]["active"] is True
        assert "max pain" in result["calendar"]["pinning_risk"]["note"]

    @pytest.mark.anyio
    async def test_pinning_risk_inactive_when_not_expiry_week(self):
        from src.market_awareness.engine import MarketAwarenessEngine

        raw_data = {
            "chart": {}, "candlestick": {}, "chart_patterns": {},
            "options": {"spot": 24205.0, "max_pain": 24200.0, "walls": {}, "iv": {}, "oi_levels": {}},
            "global": {}, "vix": {}, "calendar": {
                "expiries": {"nifty": "2026-07-30"},
                "days_to_expiry": {"nifty": 20},
            },
        }
        with patch("src.market_awareness.engine.MarketAggregator") as mock_agg_cls, \
             patch("src.market_awareness.engine.detect_market_regime", return_value={}):
            mock_agg = MagicMock()
            mock_agg.collect = AsyncMock(return_value=raw_data)
            mock_agg_cls.return_value = mock_agg

            result = await MarketAwarenessEngine().analyze("NIFTY")

        assert result["calendar"]["is_expiry_week"] is False
        assert result["calendar"]["pinning_risk"]["active"] is False
        assert result["calendar"]["pinning_risk"]["note"] is None


class TestDashboardPinningRisk:
    def test_options_section_flags_pinning_risk_during_expiry_week(self, chain_data):
        from src.dashboard import service
        from datetime import date, timedelta

        near_expiry = (date.today() + timedelta(days=2)).strftime("%d-%b-%Y")
        chain_data["records"]["expiryDates"] = [near_expiry]
        # Collapse the chain to a single strike so max_pain lands exactly at spot.
        chain_data["records"]["data"] = [
            {"strikePrice": chain_data["records"]["underlyingValue"], "expiryDate": near_expiry,
             "CE": {"openInterest": 1000}, "PE": {"openInterest": 1000}},
        ]

        with patch("src.dashboard.service.get_options_service") as mock_get_svc:
            mock_svc = MagicMock()
            mock_svc.get_option_chain.return_value = chain_data
            mock_get_svc.return_value = mock_svc

            opts, spot = service._options_section("NIFTY")

        assert opts["pinning_risk"]["active"] is True
        assert opts["pinning_risk"]["note"] is not None

    def test_options_section_unavailable_chain_has_inactive_pinning_default(self):
        from src.dashboard import service

        with patch("src.dashboard.service.get_options_service") as mock_get_svc:
            mock_svc = MagicMock()
            mock_svc.get_option_chain.return_value = {}
            mock_get_svc.return_value = mock_svc

            opts, spot = service._options_section("NIFTY")

        assert opts["pinning_risk"]["active"] is False


class TestMonitorPinningRiskAlert:
    def setup_method(self):
        from src.monitor.market_intelligence import MarketIntelligence
        self.mi = MarketIntelligence()

    def test_fires_when_active_during_expiry_week(self):
        alerts = self.mi.check_pinning_risk(
            spot=24205.0, max_pain=24200.0, is_expiry_week=True, settings={},
        )
        assert len(alerts) == 1
        assert alerts[0]["type"] == "pinning_risk"

    def test_no_alert_outside_expiry_week(self):
        alerts = self.mi.check_pinning_risk(
            spot=24205.0, max_pain=24200.0, is_expiry_week=False, settings={},
        )
        assert alerts == []

    def test_no_alert_when_far_from_max_pain(self):
        alerts = self.mi.check_pinning_risk(
            spot=24500.0, max_pain=24200.0, is_expiry_week=True, settings={},
        )
        assert alerts == []

    def test_respects_custom_threshold_setting(self):
        # 100/24300 ≈ 0.41% — inside the default 0.5% but outside a tighter 0.3%.
        alerts = self.mi.check_pinning_risk(
            spot=24300.0, max_pain=24200.0, is_expiry_week=True,
            settings={"pinning_risk_threshold_pct": 0.3},
        )
        assert alerts == []


# ---------------------------------------------------------------------------
# Priority 4 — trade-count and cost visibility
# ---------------------------------------------------------------------------


def _order(status="COMPLETE", avg_price=100.0, qty=50):
    return {
        "status": status,
        "average_price": avg_price,
        "filled_quantity": qty,
        "quantity": qty,
    }


class TestGetTradeCostEstimate:
    def _tools(self):
        from src.tools import costs

        mcp = _FastMCP("test")
        costs.register(mcp)
        return {t.name: t for t in mcp._tool_manager.list_tools()}

    def test_counts_only_completed_orders_and_estimates_brokerage(self):
        tools = self._tools()
        orders = [_order("COMPLETE"), _order("COMPLETE"), _order("OPEN"), _order("CANCELLED")]
        with patch("src.tools.costs._require_broker") as mock_require_broker:
            mock_require_broker.return_value.orders.return_value = orders
            result = tools["get_trade_cost_estimate"].fn()

        assert result["data"]["trades_today"] == 2
        assert result["data"]["estimated_brokerage"] == 40.0
        assert result["meta"]["zerodha_connected"] is True

    def test_zero_orders_yields_zero_cost_no_error(self):
        tools = self._tools()
        with patch("src.tools.costs._require_broker") as mock_require_broker:
            mock_require_broker.return_value.orders.return_value = []
            result = tools["get_trade_cost_estimate"].fn()

        assert result["data"]["trades_today"] == 0
        assert result["data"]["estimated_brokerage"] == 0.0
        assert result["data"]["estimated_total_cost"] == 0.0
        assert "error" not in result["data"]

    def test_custom_brokerage_per_order_is_respected(self):
        tools = self._tools()
        with patch("src.tools.costs._require_broker") as mock_require_broker:
            mock_require_broker.return_value.orders.return_value = [_order("COMPLETE"), _order("COMPLETE")]
            result = tools["get_trade_cost_estimate"].fn(brokerage_per_order=15.0)

        assert result["data"]["estimated_brokerage"] == 30.0
        assert result["data"]["assumptions"]["brokerage_per_order"] == 15.0

    def test_unauthenticated_broker_never_raises_returns_error_in_data(self):
        tools = self._tools()
        with patch("src.tools.costs._require_broker") as mock_require_broker:
            mock_require_broker.return_value.orders.side_effect = PermissionError("not_authenticated")
            result = tools["get_trade_cost_estimate"].fn()

        assert "error" in result["data"]
        assert result["meta"]["zerodha_connected"] is False

    def test_turnover_based_stt_estimate_present_when_orders_have_turnover(self):
        tools = self._tools()
        with patch("src.tools.costs._require_broker") as mock_require_broker:
            mock_require_broker.return_value.orders.return_value = [_order("COMPLETE", avg_price=100.0, qty=50)]
            result = tools["get_trade_cost_estimate"].fn()

        assert result["data"]["estimated_stt_charges"] is not None
        assert result["data"]["estimated_total_cost"] > result["data"]["estimated_brokerage"]


def _ind_trade(price=100.0, qty=50):
    return {"order_id": "T1", "symbol": "NIFTY24200CE", "quantity": qty, "price": price, "created_at": "", "segment": "DERIVATIVE"}


class TestGetNetPnlToday:
    """Priority B10 (2026-07-11) — gross realized P&L minus estimated costs,
    labeled distinctly so gross proceeds can't be mistaken for net profit
    (the exact confusion the task describes: ₹13,179 gross read as net
    profit when actual net after charges was ~₹1,319)."""

    def _tools(self):
        from src.tools import costs

        mcp = _FastMCP("test")
        costs.register(mcp)
        return {t.name: t for t in mcp._tool_manager.list_tools()}

    @pytest.mark.anyio
    async def test_net_pnl_subtracts_estimated_costs_from_gross(self):
        tools = self._tools()
        with patch("src.tools.costs.INDmoneyBroker") as MockInd:
            MockInd.return_value.is_authenticated = AsyncMock(return_value=True)
            MockInd.return_value.get_raw_funds = AsyncMock(return_value={
                "body": {"data": {"realized_pnl": 13179.0}},
            })
            MockInd.return_value.get_trades = AsyncMock(return_value=[_ind_trade()] * 30)

            result = await tools["get_net_pnl_today"].fn()

        data = result["data"]
        assert data["gross_realized_pnl"] == 13179.0
        assert data["net_pnl_estimate"] == data["gross_realized_pnl"] - data["estimated_total_cost"]
        assert data["net_pnl_estimate"] < data["gross_realized_pnl"]

    @pytest.mark.anyio
    async def test_gross_and_net_are_distinctly_labeled_fields(self):
        """The exact confusion the task describes must be structurally
        impossible — gross and net are different, clearly-named keys."""
        tools = self._tools()
        with patch("src.tools.costs.INDmoneyBroker") as MockInd:
            MockInd.return_value.is_authenticated = AsyncMock(return_value=True)
            MockInd.return_value.get_raw_funds = AsyncMock(return_value={
                "body": {"data": {"realized_pnl": 1000.0}},
            })
            MockInd.return_value.get_trades = AsyncMock(return_value=[])

            result = await tools["get_net_pnl_today"].fn()

        assert "gross_realized_pnl" in result["data"]
        assert "net_pnl_estimate" in result["data"]
        assert result["data"]["gross_realized_pnl"] != result["data"].get("estimated_total_cost")

    @pytest.mark.anyio
    async def test_zero_trades_yields_zero_cost_net_equals_gross(self):
        tools = self._tools()
        with patch("src.tools.costs.INDmoneyBroker") as MockInd:
            MockInd.return_value.is_authenticated = AsyncMock(return_value=True)
            MockInd.return_value.get_raw_funds = AsyncMock(return_value={
                "body": {"data": {"realized_pnl": 500.0}},
            })
            MockInd.return_value.get_trades = AsyncMock(return_value=[])

            result = await tools["get_net_pnl_today"].fn()

        assert result["data"]["estimated_total_cost"] == 0.0
        assert result["data"]["net_pnl_estimate"] == 500.0

    @pytest.mark.anyio
    async def test_unauthenticated_never_raises(self):
        tools = self._tools()
        with patch("src.tools.costs.INDmoneyBroker") as MockInd:
            MockInd.return_value.is_authenticated = AsyncMock(return_value=False)

            result = await tools["get_net_pnl_today"].fn()

        assert "error" in result["data"]
        assert result["meta"]["data_quality"] == _meta.DQ_INVALID

    @pytest.mark.anyio
    async def test_missing_funds_data_defaults_to_zero_gross(self):
        tools = self._tools()
        with patch("src.tools.costs.INDmoneyBroker") as MockInd:
            MockInd.return_value.is_authenticated = AsyncMock(return_value=True)
            MockInd.return_value.get_raw_funds = AsyncMock(return_value={})
            MockInd.return_value.get_trades = AsyncMock(return_value=[])

            result = await tools["get_net_pnl_today"].fn()

        assert result["data"]["gross_realized_pnl"] == 0.0
        assert "error" not in result["data"]

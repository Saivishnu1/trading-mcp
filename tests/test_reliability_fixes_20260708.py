"""
Regression tests for 4 reliability issues found during a live session (2026-07-08):

1. get_market_awareness — chart/indicator failure collapsed to zeros instead of nulls.
2. get_sensex_dashboard NoneType crash (PCR chain) + calculate_atr misleading error.
3. spot price vs day_high/day_low sanity check.
4. meta.zerodha_connected stuck at False / hardcoded True.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from mcp.server.fastmcp import FastMCP as _FastMCP

from src.market_awareness.engine import MarketAwarenessEngine
from src import meta as _meta


# ---------------------------------------------------------------------------
# 1. Chart failure -> null indicators, not zeros
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_market_awareness_chart_failure_yields_nulls_not_zeros():
    """When the chart engine fails, indicators must be None, not 0.0 —
    a real ADX/RSI/ATR of exactly zero is indistinguishable from "unknown"
    if we silently coerce failures to 0.0."""
    mock_chart_engine = MagicMock()
    mock_chart_engine.analyze = AsyncMock(return_value={
        "error": "No data available for this symbol/interval combination",
        "trend": {}, "structure": {}, "indicators": {}, "levels": {},
    })
    mock_options_engine = MagicMock()
    mock_options_engine.analyze = MagicMock(return_value={"spot": 24270.0, "pcr": 1.0})
    mock_regime = MagicMock(return_value={})

    with patch("src.market_awareness.aggregator.ChartEngine", return_value=mock_chart_engine), \
         patch("src.market_awareness.aggregator.OptionsAwarenessEngine", return_value=mock_options_engine), \
         patch("src.market_awareness.aggregator.get_global_pulse", MagicMock(return_value={})), \
         patch("src.market_awareness.aggregator.get_india_vix", MagicMock(return_value={})), \
         patch("src.market_awareness.aggregator.get_market_calendar", MagicMock(return_value={})), \
         patch("src.market_awareness.engine.detect_market_regime", mock_regime):

        engine = MarketAwarenessEngine()
        res = await engine.analyze("NIFTY")

        assert "chart" in res["missing_data"]
        assert res["market_structure"]["adx"] is None
        assert res["indicators"]["rsi"] is None
        assert res["indicators"]["macd"] is None
        assert res["indicators"]["atr"] is None
        assert res["indicators"]["ema20"] is None
        assert res["indicators"]["ema200"] is None


def test_yfinance_download_retries_before_failing():
    """The core yfinance historical fetch must retry rather than fail on the
    first transient error."""
    from src.market import service as market_service

    call_count = {"n": 0}

    def _flaky_download(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] < 3:
            raise RuntimeError("simulated yfinance rate limit")
        import pandas as pd
        return pd.DataFrame()

    with patch("yfinance.download", side_effect=_flaky_download), \
         patch("time.sleep", return_value=None):
        svc = market_service.MarketService()
        result = svc.get_historical("NIFTY", "2026-01-01", "2026-01-10", "1d")

    assert call_count["n"] == 3
    assert result == []


# ---------------------------------------------------------------------------
# 2. Sensex dashboard NoneType guard + calculate_atr clearer error
# ---------------------------------------------------------------------------

def test_pcr_component_routes_sensex_to_bse_options_service():
    from src.intelligence import risk as risk_mod

    mock_bse_svc = MagicMock()
    mock_bse_svc.get_option_chain.return_value = {
        "records": {"expiryDates": ["31-Jul-2026"]}
    }
    mock_nse_svc = MagicMock()

    with patch("src.options.bse_service.get_bse_options_service", return_value=mock_bse_svc), \
         patch("src.options.service.get_options_service", return_value=mock_nse_svc), \
         patch("src.options.analytics.calculate_pcr", return_value={"pcr_sentiment_code": "NEUTRAL", "interpretation": "neutral"}):
        risk_mod._pcr_component("SENSEX")

    mock_bse_svc.get_option_chain.assert_called_once_with("SENSEX")
    mock_nse_svc.get_option_chain.assert_not_called()


def test_pcr_component_handles_none_chain_without_crashing():
    """Root cause of the 'NoneType has no attribute get' crash: a chain fetch
    that returns None (or any non-dict) must degrade gracefully, not raise."""
    from src.intelligence import risk as risk_mod

    mock_svc = MagicMock()
    mock_svc.get_option_chain.return_value = None

    with patch("src.options.service.get_options_service", return_value=mock_svc):
        score, desc, ok = risk_mod._pcr_component("NIFTY")

    assert score == 50
    assert ok is False


def test_calculate_atr_error_message_distinguishes_source_failure_from_bad_symbol():
    from src.tools import technicals

    mcp = _FastMCP("test")
    technicals.register(mcp)
    tools = {t.name: t for t in mcp._tool_manager.list_tools()}

    with patch("src.tools.technicals._load_closes", return_value=(None, None, None)):
        result = tools["calculate_atr"].fn("NIFTY")

    msg = result["data"]["error"]
    assert "check the symbol" not in msg or "temporarily unavailable" in msg
    assert "temporarily unavailable" in msg or "rate-limited" in msg


def test_load_candles_falls_back_to_indmoney_when_yfinance_empty():
    from src.tools import technicals

    fallback_candles = [
        {"datetime": "2026-07-01", "open": 100.0, "high": 105.0, "low": 99.0, "close": 104.0, "volume": 1000},
    ]

    with patch("src.tools.technicals.get_market") as mock_get_market:
        mock_get_market.return_value.get_historical.return_value = []
        with patch(
            "src.chart_awareness.data_fetcher.fetch_candles",
            new=AsyncMock(return_value=(fallback_candles, "indmoney")),
        ):
            result = technicals._load_candles("NIFTY", 60)

    assert len(result) == 1
    assert result[0]["close"] == 104.0


# ---------------------------------------------------------------------------
# 3. Spot price sanity check
# ---------------------------------------------------------------------------

class TestSpotOutsideRange:
    def test_spot_within_range_is_not_suspect(self):
        assert _meta.spot_outside_range(24000.0, 24100.0, 23900.0) is False

    def test_spot_above_high_is_suspect(self):
        assert _meta.spot_outside_range(24200.0, 24100.0, 23900.0) is True

    def test_spot_below_low_is_suspect(self):
        assert _meta.spot_outside_range(23800.0, 24100.0, 23900.0) is True

    def test_missing_values_are_not_suspect(self):
        assert _meta.spot_outside_range(None, 24100.0, 23900.0) is False
        assert _meta.spot_outside_range(24000.0, None, 23900.0) is False
        assert _meta.spot_outside_range(24000.0, 24100.0, None) is False


@pytest.mark.anyio
async def test_get_market_awareness_flags_suspect_spot_price():
    from src.tools import market_awareness

    mcp = _FastMCP("test")
    market_awareness.register(mcp)
    tools = {t.name: t for t in mcp._tool_manager.list_tools()}

    mismatched_result = {
        "symbol": "NIFTY",
        "spot": 23918.0,
        "day_high": 24100.0,
        "day_low": 24000.0,
    }

    mock_engine = MagicMock()
    mock_engine.analyze = AsyncMock(return_value=mismatched_result)

    with patch("src.tools.market_awareness.MarketAwarenessEngine", return_value=mock_engine):
        result = await tools["get_market_awareness"].fn(symbol="NIFTY")

    assert result["meta"]["data_quality"] == _meta.DQ_SUSPECT
    assert "day_high" in result["meta"]["warning"] or "outside" in result["meta"]["warning"].lower()


# ---------------------------------------------------------------------------
# 4. zerodha_connected wiring
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_unified_holdings_reports_zerodha_connected_true_when_authenticated():
    from src.tools import brokers

    mcp = _FastMCP("test")
    brokers.register(mcp)
    tools = {t.name: t for t in mcp._tool_manager.list_tools()}

    mock_zerodha = MagicMock()
    mock_zerodha.is_authenticated = AsyncMock(return_value=True)
    mock_indmoney = MagicMock()
    mock_indmoney.is_authenticated = AsyncMock(return_value=False)

    with patch("src.tools.brokers.ZerodhaBroker", return_value=mock_zerodha), \
         patch("src.tools.brokers.INDmoneyBroker", return_value=mock_indmoney), \
         patch("src.tools.brokers._fetch_broker_data", new=AsyncMock(return_value={"data": [], "status": "ok"})):
        result = await tools["get_unified_holdings"].fn(broker="zerodha")

    assert result["meta"]["zerodha_connected"] is True


@pytest.mark.anyio
async def test_unified_holdings_reports_zerodha_connected_false_when_not_authenticated():
    from src.tools import brokers

    mcp = _FastMCP("test")
    brokers.register(mcp)
    tools = {t.name: t for t in mcp._tool_manager.list_tools()}

    mock_zerodha = MagicMock()
    mock_zerodha.is_authenticated = AsyncMock(return_value=False)

    with patch("src.tools.brokers.ZerodhaBroker", return_value=mock_zerodha):
        result = await tools["get_unified_holdings"].fn(broker="zerodha")

    assert result["meta"]["zerodha_connected"] is False


def test_get_orders_zerodha_connected_reflects_actual_call_success():
    from src.tools import journal

    mcp = _FastMCP("test")
    journal.register(mcp)
    tools = {t.name: t for t in mcp._tool_manager.list_tools()}

    with patch("src.tools.journal._require_user", return_value=True), \
         patch("src.tools.journal._require_broker") as mock_require_broker:
        mock_require_broker.return_value.orders.side_effect = RuntimeError("no session")
        result = tools["get_orders"].fn()

    assert result["meta"]["zerodha_connected"] is False
    assert "error" in result["data"]


def test_get_broker_status_zerodha_connected_matches_status_payload():
    from src.tools import brokers

    mcp = _FastMCP("test")
    brokers.register(mcp)
    tools = {t.name: t for t in mcp._tool_manager.list_tools()}

    async def _fake_status():
        return {"zerodha": {"authenticated": True}, "indmoney": {"authenticated": False}}

    async def _run():
        with patch("src.tools.brokers._get_broker_status", new=_fake_status):
            return await tools["get_broker_status"].fn()

    import asyncio
    result = asyncio.run(_run())

    assert result["meta"]["zerodha_connected"] is True

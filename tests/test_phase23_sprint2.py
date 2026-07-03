"""
Phase 23B Sprint 2 — tests for pre-conditions and new tools.

Pre-condition 1 : TOOL_TIME_GATED error contract on 4 technicals tools
Pre-condition 2 : Symbol metadata propagation gaps in generate_trade_setup
Sprint 2 D1     : get_option_chain_depth
Sprint 2 D2     : get_intraday_snapshot
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from mcp.server.fastmcp import FastMCP as _FastMCP


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tech_mcp():
    from src.tools import technicals
    mcp = _FastMCP("test")
    technicals.register(mcp)
    return {t.name: t for t in mcp._tool_manager.list_tools()}


def _opts_mcp():
    from src.tools import options
    mcp = _FastMCP("test")
    options.register(mcp)
    return {t.name: t for t in mcp._tool_manager.list_tools()}


def _market_mcp():
    from src.tools import market
    mcp = _FastMCP("test")
    market.register(mcp)
    return {t.name: t for t in mcp._tool_manager.list_tools()}



# ---------------------------------------------------------------------------
# Pre-condition 1 — TOOL_TIME_GATED error contract
# ---------------------------------------------------------------------------

class TestToolTimeGatedContract:
    """When is_market_hours() returns False, time-gated tools return TOOL_TIME_GATED."""

    def _call_outside_hours(self, tool_name, fn, *args, **kwargs):
        with patch("src.meta.is_market_hours", return_value=False):
            return fn(*args, **kwargs)

    def test_calculate_rsi_time_gated_structure(self):
        tools = _tech_mcp()
        result = self._call_outside_hours("calculate_rsi", tools["calculate_rsi"].fn, "INFY", period=14)
        assert result.get("status") == "TOOL_TIME_GATED"
        assert "available_from" in result
        assert "available_until" in result
        assert result.get("tool") == "calculate_rsi"

    def test_calculate_ema_time_gated_structure(self):
        tools = _tech_mcp()
        result = self._call_outside_hours("calculate_ema", tools["calculate_ema"].fn, "INFY", period=20)
        assert result.get("status") == "TOOL_TIME_GATED"
        assert result.get("tool") == "calculate_ema"

    def test_calculate_macd_time_gated_structure(self):
        tools = _tech_mcp()
        result = self._call_outside_hours("calculate_macd", tools["calculate_macd"].fn, "INFY")
        assert result.get("status") == "TOOL_TIME_GATED"
        assert result.get("tool") == "calculate_macd"

    def test_analyze_technicals_time_gated_structure(self):
        tools = _tech_mcp()
        result = self._call_outside_hours("analyze_technicals", tools["analyze_technicals"].fn, "INFY")
        assert result.get("status") == "TOOL_TIME_GATED"
        assert result.get("tool") == "analyze_technicals"

    def test_all_four_identical_keys(self):
        """All four tools return the same set of TOOL_TIME_GATED keys."""
        tools = _tech_mcp()
        fns = [
            (tools["calculate_rsi"].fn, ("INFY",), {"period": 14}),
            (tools["calculate_ema"].fn, ("INFY",), {"period": 20}),
            (tools["calculate_macd"].fn, ("INFY",), {}),
            (tools["analyze_technicals"].fn, ("INFY",), {}),
        ]
        key_sets = []
        with patch("src.meta.is_market_hours", return_value=False):
            for fn, args, kwargs in fns:
                result = fn(*args, **kwargs)
                key_sets.append(frozenset(result.keys()))
        assert len(set(key_sets)) == 1, f"key sets differ: {key_sets}"

    def test_symbol_error_takes_precedence_over_time_gate(self):
        """Empty symbol → SYMBOL_ERROR, not TOOL_TIME_GATED."""
        tools = _tech_mcp()
        with patch("src.meta.is_market_hours", return_value=False):
            result = tools["calculate_rsi"].fn("", period=14)
        assert result.get("status") == "SYMBOL_ERROR"

    def test_time_gated_tools_in_meta_tools_list(self):
        """meta_tools._TIME_GATED includes all four technicals tools."""
        from src.tools.meta_tools import _TIME_GATED
        for name in ("calculate_rsi", "calculate_ema", "calculate_macd", "analyze_technicals"):
            assert name in _TIME_GATED, f"{name} missing from _TIME_GATED"


# ---------------------------------------------------------------------------
# D1 — get_option_chain_depth
# ---------------------------------------------------------------------------

TEST_EXPIRY = "26-Jun-2025"
TEST_SPOT = 24000.0


def _make_chain_data(spot=TEST_SPOT, expiry=TEST_EXPIRY):
    rows = []
    for strike in range(23500, 24600, 100):
        rows.append({
            "strikePrice": float(strike),
            "expiryDate": expiry,
            "CE": {
                "openInterest": 10000,
                "changeinOpenInterest": 500,
                "totalTradedVolume": 2000,
                "impliedVolatility": 14.5,
                "lastPrice": max(0.05, (24500 - strike) / 100),
            },
            "PE": {
                "openInterest": 8000,
                "changeinOpenInterest": -300,
                "totalTradedVolume": 1500,
                "impliedVolatility": 15.0,
                "lastPrice": max(0.05, (strike - 23500) / 100),
            },
        })
    return {
        "records": {
            "data": rows,
            "expiryDates": [expiry],
            "underlyingValue": spot,
        }
    }


class TestGetOptionChainDepth:
    def setup_method(self):
        self.tools = _opts_mcp()
        self.fn = self.tools["get_option_chain_depth"].fn

    def _call(self, symbol="NIFTY", expiry=TEST_EXPIRY, atm_range=5):
        chain = _make_chain_data()
        svc = MagicMock()
        svc.get_option_chain.return_value = chain
        with patch("src.tools.options.get_options_service", return_value=svc):
            return self.fn(symbol=symbol, expiry=expiry, atm_range=atm_range)

    def test_tool_registered(self):
        assert "get_option_chain_depth" in self.tools

    def test_response_has_data_and_meta(self):
        result = self._call()
        assert "data" in result
        assert "meta" in result

    def test_data_has_required_keys(self):
        d = self._call()["data"]
        assert "symbol" in d
        assert "spot" in d
        assert "expiry" in d
        assert "atm_strike" in d
        assert "strikes" in d
        assert "summary" in d
        assert "limitations" in d

    def test_summary_keys(self):
        s = self._call()["data"]["summary"]
        assert "atm_strike" in s
        assert "max_pain" in s
        assert "pcr_oi" in s
        assert "pcr_volume" in s

    def test_per_strike_keys(self):
        strikes = self._call()["data"]["strikes"]
        assert len(strikes) > 0
        row = strikes[0]
        for key in ("strike", "call_oi", "call_oi_change", "call_volume",
                    "call_iv", "call_ltp", "put_oi", "put_oi_change",
                    "put_volume", "put_iv", "put_ltp"):
            assert key in row, f"missing key: {key}"

    def test_atm_range_filters_strikes(self):
        result_5 = self._call(atm_range=5)
        result_0 = self._call(atm_range=0)
        assert len(result_5["data"]["strikes"]) <= len(result_0["data"]["strikes"])

    def test_limitations_is_list(self):
        assert isinstance(self._call()["data"]["limitations"], list)

    def test_meta_has_freshness(self):
        assert "freshness" in self._call()["meta"]

    def test_meta_source_is_nse(self):
        assert self._call()["meta"]["source"] == "NSE"

    def test_stale_threshold_60s(self):
        m = self._call()["meta"]
        assert m["freshness"]["stale_threshold_seconds"] == 60

    def test_no_signals_in_data(self):
        d = self._call()["data"]
        for key in ("signal", "confidence", "interpretation", "recommendation"):
            assert key not in d, f"forbidden key in data: {key}"

    def test_empty_symbol_returns_symbol_error(self):
        result = self.fn(symbol="")
        assert result.get("status") == "SYMBOL_ERROR"

    def test_service_error_returns_error_in_data(self):
        svc = MagicMock()
        svc.get_option_chain.side_effect = RuntimeError("NSE blocked")
        with patch("src.tools.options.get_options_service", return_value=svc):
            result = self.fn(symbol="NIFTY")
        assert "error" in result["data"]

    def test_symbol_normalization_in_meta(self):
        result = self._call(symbol="NSE:NIFTY")
        meta = result["meta"]
        assert meta.get("symbol_corrected") is True


# ---------------------------------------------------------------------------
# D2 — get_intraday_snapshot
# ---------------------------------------------------------------------------

_MOCK_QUOTE = {
    "instrument": "NSE:INFY",
    "last_price": 1850.0,
    "open": 1820.0,
    "high": 1870.0,
    "low": 1810.0,
    "close": None,
    "previous_close": 1800.0,
    "change": 50.0,
    "change_percent": 2.78,
    "volume": 500000,
    "source": "NSELive",
}


class TestGetIntradaySnapshot:
    def setup_method(self):
        self.tools = _market_mcp()
        self.fn = self.tools["get_intraday_snapshot"].fn

    def _call(self, symbol="NSE:INFY"):
        with patch("src.market.service.MarketService.get_quote", return_value=_MOCK_QUOTE):
            return self.fn(symbol)

    def test_tool_registered(self):
        assert "get_intraday_snapshot" in self.tools

    def test_response_has_data_and_meta(self):
        result = self._call()
        assert "data" in result
        assert "meta" in result

    def test_required_fields_present(self):
        d = self._call()["data"]
        for key in ("open", "high", "low", "current", "day_range_pct",
                    "distance_from_day_high", "distance_from_day_low",
                    "distance_from_vwap"):
            assert key in d, f"missing field: {key}"

    def test_vwap_flagged_null(self):
        d = self._call()["data"]
        assert d["distance_from_vwap"] is None

    def test_day_range_pct_computed(self):
        d = self._call()["data"]
        # (1870 - 1810) / 1810 * 100
        expected = round((1870 - 1810) / 1810 * 100, 4)
        assert abs(d["day_range_pct"] - expected) < 0.01

    def test_distance_from_day_high_negative(self):
        d = self._call()["data"]
        # current (1850) < high (1870) → negative distance
        assert d["distance_from_day_high"] < 0

    def test_distance_from_day_low_positive(self):
        d = self._call()["data"]
        # current (1850) > low (1810) → positive distance
        assert d["distance_from_day_low"] > 0

    def test_limitations_lists_vwap_unavailable(self):
        d = self._call()["data"]
        lims = d["limitations"]
        assert any("VWAP" in s or "vwap" in s.lower() for s in lims)

    def test_meta_has_freshness(self):
        assert "freshness" in self._call()["meta"]

    def test_no_signals_in_data(self):
        d = self._call()["data"]
        for key in ("signal", "confidence", "interpretation", "recommendation"):
            assert key not in d, f"forbidden key in data: {key}"

    def test_time_gated_outside_hours(self):
        with patch("src.meta.is_market_hours", return_value=False):
            result = self.fn("INFY")
        assert result.get("status") == "TOOL_TIME_GATED"
        assert result.get("tool") == "get_intraday_snapshot"

    def test_empty_symbol_returns_symbol_error(self):
        result = self.fn("")
        assert result.get("status") == "SYMBOL_ERROR"

    def test_in_time_gated_list(self):
        from src.tools.meta_tools import _TIME_GATED
        assert "get_intraday_snapshot" in _TIME_GATED

    def test_symbol_corrected_in_meta(self):
        # Bare "INFY" → corrected to "NSE:INFY" by get_quote format normalization
        with patch("src.market.service.MarketService.get_quote", return_value=_MOCK_QUOTE):
            result = self.fn("INFY")
        assert result["meta"].get("symbol_corrected") is True


# ---------------------------------------------------------------------------
# get_capabilities reflects new tools
# ---------------------------------------------------------------------------

class TestCapabilitiesReflectNewTools:
    def setup_method(self):
        from src.tools.meta_tools import register as _reg
        mcp = _FastMCP("test")
        _reg(mcp)
        tools = {t.name: t for t in mcp._tool_manager.list_tools()}
        fn = tools["get_capabilities"].fn
        self.result = fn()

    def test_option_chain_depth_capability_true(self):
        caps = self.result["data"]["capabilities"]
        assert caps.get("option_chain_depth") is True

    def test_intraday_snapshot_capability_true(self):
        caps = self.result["data"]["capabilities"]
        assert caps.get("intraday_snapshot") is True

    def test_time_gated_includes_new_tools(self):
        tg = self.result["data"]["time_gated"]
        assert "get_intraday_snapshot" in tg

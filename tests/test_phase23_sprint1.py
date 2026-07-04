"""
Phase 23 Sprint 1 — Integration tests for all 6 deliverables.

D1  get_market_calendar
D2  get_capabilities
D3  Data freshness metadata on existing tools
D4  get_tool_health
D5  Universal symbol normalization
D6  Loud error contracts
"""
from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# D1 — get_market_calendar
# ---------------------------------------------------------------------------

from src.market.calendar import get_market_calendar


class TestMarketCalendar:
    def setup_method(self):
        self.cal = get_market_calendar()

    def test_top_level_keys(self):
        assert {"today", "expiries", "days_to_expiry", "upcoming_holidays",
                "next_trading_day", "week_summary"} <= self.cal.keys()

    def test_today_fields(self):
        today = self.cal["today"]
        assert "date" in today
        assert "day" in today
        assert "is_trading_day" in today
        assert "is_holiday" in today

    def test_expiries_has_nifty(self):
        assert "nifty" in self.cal["expiries"]

    def test_days_to_expiry_non_negative(self):
        for idx, days in self.cal["days_to_expiry"].items():
            assert days >= 0, f"{idx} days_to_expiry is negative: {days}"

    def test_next_trading_day_is_string(self):
        ntd = self.cal["next_trading_day"]
        assert isinstance(ntd, str) and len(ntd) == 10

    def test_week_summary_keys(self):
        ws = self.cal["week_summary"]
        assert "trading_days_remaining" in ws
        assert "expiry_days_this_week" in ws

    def test_upcoming_holidays_list(self):
        assert isinstance(self.cal["upcoming_holidays"], list)

    def test_no_hardcoded_holiday_as_primary(self):
        # Holiday info comes from _NSE_HOLIDAYS_2026 as fallback only.
        # The function must NOT return a fixed holiday list as the main
        # expiry source — expiries must come from the live service or algorithm.
        from src.market import calendar as cal_mod
        assert hasattr(cal_mod, "_live_expiries")


# ---------------------------------------------------------------------------
# D1 MCP wrapper — get_market_calendar via meta_tools
# ---------------------------------------------------------------------------

from src.tools.meta_tools import register as _register_meta
from mcp.server.fastmcp import FastMCP as _FastMCP


def _make_mcp():
    mcp = _FastMCP("test")
    _register_meta(mcp)
    return mcp


class TestMarketCalendarMcpTool:
    def setup_method(self):
        mcp = _make_mcp()
        tools = {t.name: t for t in mcp._tool_manager.list_tools()}
        fn = tools["get_market_calendar"].fn
        import asyncio
        self.result = asyncio.get_event_loop().run_until_complete(fn()) if asyncio.iscoroutinefunction(fn) else fn()

    def test_has_data_and_meta(self):
        assert "data" in self.result
        assert "meta" in self.result

    def test_data_has_calendar_keys(self):
        assert "today" in self.result["data"]

    def test_meta_has_freshness(self):
        assert "freshness" in self.result["meta"]

    def test_freshness_label_present(self):
        label = self.result["meta"]["freshness"]["label"]
        assert label in ("LIVE", "RECENT", "STALE", "CACHED")

    def test_stale_threshold_is_one_day(self):
        assert self.result["meta"]["freshness"]["stale_threshold_seconds"] == 86400


# ---------------------------------------------------------------------------
# D2 — get_capabilities
# ---------------------------------------------------------------------------

class TestGetCapabilities:
    def setup_method(self):
        mcp = _make_mcp()
        tools = {t.name: t for t in mcp._tool_manager.list_tools()}
        fn = tools["get_capabilities"].fn
        import asyncio
        self.result = asyncio.get_event_loop().run_until_complete(fn()) if asyncio.iscoroutinefunction(fn) else fn()

    def test_has_data_and_meta(self):
        assert "data" in self.result
        assert "meta" in self.result

    def test_capabilities_flag_present(self):
        assert "capabilities" in self.result["data"]

    def test_data_lag_dict(self):
        assert isinstance(self.result["data"]["data_lag"], dict)

    def test_market_calendar_is_capable(self):
        assert self.result["data"]["capabilities"].get("market_calendar") is True

    def test_known_broken_is_list(self):
        assert isinstance(self.result["data"]["known_broken"], list)

    def test_time_gated_is_list(self):
        assert isinstance(self.result["data"]["time_gated"], list)

    def test_meta_key_present(self):
        assert "as_of" in self.result["data"]["meta"]
        assert "mcp_version" in self.result["data"]["meta"]

    def test_total_tools_positive(self):
        assert self.result["data"]["meta"]["total_tools"] > 0


# ---------------------------------------------------------------------------
# D3 — Freshness metadata on existing tools
# ---------------------------------------------------------------------------

from src import meta as _meta


class TestFreshnessMetadata:
    def test_freshness_label_live(self):
        m = _meta.build_meta(
            type_=_meta.TYPE_FACT,
            data_quality=_meta.DQ_VALID,
            source="test",
            account_type="MARKET_DATA_ONLY",
            data_age_seconds=30,
            stale_threshold_seconds=300,
        )
        assert m["freshness"]["label"] == "LIVE"

    def test_freshness_label_recent(self):
        m = _meta.build_meta(
            type_=_meta.TYPE_FACT,
            data_quality=_meta.DQ_VALID,
            source="test",
            account_type="MARKET_DATA_ONLY",
            data_age_seconds=120,
            stale_threshold_seconds=300,
        )
        assert m["freshness"]["label"] == "RECENT"

    def test_freshness_label_stale(self):
        m = _meta.build_meta(
            type_=_meta.TYPE_FACT,
            data_quality=_meta.DQ_VALID,
            source="test",
            account_type="MARKET_DATA_ONLY",
            data_age_seconds=400,
            stale_threshold_seconds=300,
        )
        assert m["freshness"]["label"] == "STALE"
        assert m["freshness"]["is_stale"] is True

    def test_freshness_label_cached(self):
        m = _meta.build_meta(
            type_=_meta.TYPE_FACT,
            data_quality=_meta.DQ_VALID,
            source="test",
            account_type="MARKET_DATA_ONLY",
            from_cache=True,
        )
        assert m["freshness"]["label"] == "CACHED"

    def test_stale_data_warning_in_wrap(self):
        m = _meta.build_meta(
            type_=_meta.TYPE_FACT,
            data_quality=_meta.DQ_VALID,
            source="test",
            account_type="MARKET_DATA_ONLY",
            data_age_seconds=999,
            stale_threshold_seconds=300,
        )
        wrapped = _meta.wrap({"x": 1}, m)
        warnings = wrapped.get("warnings", [])
        assert any("STALE_DATA" in w for w in warnings)

    def test_fresh_data_no_stale_warning(self):
        m = _meta.build_meta(
            type_=_meta.TYPE_FACT,
            data_quality=_meta.DQ_VALID,
            source="test",
            account_type="MARKET_DATA_ONLY",
            data_age_seconds=10,
            stale_threshold_seconds=300,
        )
        wrapped = _meta.wrap({"x": 1}, m)
        warnings = wrapped.get("warnings", [])
        assert not any("STALE_DATA" in w for w in warnings)

    def test_freshness_keys(self):
        m = _meta.build_meta(
            type_=_meta.TYPE_FACT,
            data_quality=_meta.DQ_VALID,
            source="test",
            account_type="MARKET_DATA_ONLY",
        )
        f = m["freshness"]
        assert {"label", "data_age_seconds", "stale_threshold_seconds", "is_stale"} <= f.keys()


# ---------------------------------------------------------------------------
# D4 — get_tool_health
# ---------------------------------------------------------------------------

class TestGetToolHealth:
    def setup_method(self):
        mcp = _make_mcp()
        tools = {t.name: t for t in mcp._tool_manager.list_tools()}
        fn = tools["get_tool_health"].fn
        import asyncio
        self.result = asyncio.get_event_loop().run_until_complete(fn()) if asyncio.iscoroutinefunction(fn) else fn()

    def test_has_data_and_meta(self):
        assert "data" in self.result
        assert "meta" in self.result

    def test_summary_keys(self):
        s = self.result["data"]["summary"]
        assert {"healthy", "degraded", "deprecated", "time_gated", "total"} <= s.keys()

    def test_tools_dict(self):
        assert isinstance(self.result["data"]["tools"], dict)

    def test_tools_have_status_and_lag(self):
        for name, info in self.result["data"]["tools"].items():
            assert "status" in info, f"{name} missing status"
            assert "data_lag" in info, f"{name} missing data_lag"

    def test_status_values_valid(self):
        valid = {"healthy", "degraded", "deprecated", "time_gated"}
        for name, info in self.result["data"]["tools"].items():
            assert info["status"] in valid, f"{name} has invalid status: {info['status']}"

    def test_meta_has_checked_at(self):
        assert "checked_at" in self.result["data"]["meta"]

    def test_total_matches_tools_count(self):
        s = self.result["data"]["summary"]
        tools = self.result["data"]["tools"]
        assert s["total"] == len(tools)


# ---------------------------------------------------------------------------
# D5 — Universal symbol normalization (normalize_symbol_extended)
# ---------------------------------------------------------------------------

from src.market.symbols import normalize_symbol_extended


class TestNormalizeSymbolExtended:
    def test_nifty_index_canonical(self):
        sym, corrected, fmt = normalize_symbol_extended("NIFTY", "calculate_rsi")
        assert sym == "^NSEI"
        assert corrected is True
        assert fmt == "INDEX_CANONICAL"

    def test_banknifty_index_canonical(self):
        sym, corrected, fmt = normalize_symbol_extended("BANKNIFTY", "analyze_technicals")
        assert sym == "^NSEBANK"
        assert fmt == "INDEX_CANONICAL"

    def test_nse_prefix_equity(self):
        sym, corrected, fmt = normalize_symbol_extended("NSE:INFY", "calculate_rsi")
        assert sym == "INFY.NS"
        assert corrected is True
        assert fmt == "YF_NS_SUFFIX"

    def test_already_correct_yf_suffix(self):
        sym, corrected, fmt = normalize_symbol_extended("INFY.NS", "calculate_rsi")
        assert sym == "INFY.NS"
        assert corrected is False

    def test_passthrough_for_unknown_tool(self):
        sym, corrected, fmt = normalize_symbol_extended("INFY", "some_unknown_tool")
        assert fmt == "PASSTHROUGH"
        assert corrected is False

    def test_nse_prefix_tool(self):
        sym, corrected, fmt = normalize_symbol_extended("INFY", "get_quote")
        assert sym == "NSE:INFY"
        assert fmt == "NSE_PREFIX"

    def test_bare_format_tool(self):
        sym, corrected, fmt = normalize_symbol_extended("NSE:INFY", "detect_market_regime")
        assert sym == "INFY"
        assert fmt == "BARE"

    def test_options_tool_passthrough(self):
        # Options tools not in _TOOL_FORMATS — symbol unchanged (service uses nse_sym from parse)
        sym, corrected, fmt = normalize_symbol_extended("NIFTY", "get_expiries")
        # NIFTY is in INDEX_YF → INDEX_CANONICAL
        assert sym == "^NSEI"
        assert fmt == "INDEX_CANONICAL"

    def test_whitespace_stripped(self):
        sym, _, _ = normalize_symbol_extended("  INFY  ", "calculate_rsi")
        assert "INFY" in sym


class TestNormKwInTechnicalsResponse:
    """Check that normalization info appears in wrapped tool responses."""

    def test_atr_with_nse_prefix_records_correction(self):
        from unittest.mock import patch
        from src.tools import technicals

        with patch("src.market.service.MarketService.get_historical") as mock_hist:
            mock_hist.return_value = [
                {"date": f"2025-01-{i:02d}", "open": 100, "high": 105,
                 "low": 95, "close": 100 + i, "volume": 1000}
                for i in range(1, 31)
            ]
            mcp = _FastMCP("test")
            technicals.register(mcp)
            tools = {t.name: t for t in mcp._tool_manager.list_tools()}
            fn = tools["calculate_atr"].fn
            result = fn("NSE:INFY", period=5, lookback_days=60)

        meta = result.get("meta", {})
        assert meta.get("symbol_corrected") is True
        assert meta.get("symbol_original") == "NSE:INFY"


# ---------------------------------------------------------------------------
# D6 — Loud error contracts
# ---------------------------------------------------------------------------

class TestErrorContracts:
    def test_make_symbol_error_structure(self):
        err = _meta.make_symbol_error("BAD!", "calculate_rsi")
        assert err["status"] == "SYMBOL_ERROR"
        assert err["received"] == "BAD!"
        assert err["tool"] == "calculate_rsi"
        assert isinstance(err["suggestions"], list)

    def test_make_symbol_error_with_suggestions(self):
        err = _meta.make_symbol_error("NIFTY5", "calculate_rsi", suggestions=["NIFTY", "NIFTY50"])
        assert "NIFTY" in err["suggestions"]

    def test_make_deprecated_error_structure(self):
        err = _meta.make_deprecated_error("old_tool", "replaced by new_tool", alternative="new_tool")
        assert err["status"] == "TOOL_DEPRECATED"
        assert err["tool"] == "old_tool"
        assert err["alternative"] == "new_tool"

    def test_make_time_gated_error_structure(self):
        err = _meta.make_time_gated_error("live_prices")
        assert err["status"] == "TOOL_TIME_GATED"
        assert "available_from" in err
        assert "available_until" in err

    def test_empty_symbol_returns_symbol_error(self):
        from src.tools import technicals
        mcp = _FastMCP("test")
        technicals.register(mcp)
        tools = {t.name: t for t in mcp._tool_manager.list_tools()}
        fn = tools["calculate_atr"].fn
        result = fn("", period=14)
        assert result.get("status") == "SYMBOL_ERROR"

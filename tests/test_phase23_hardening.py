"""
Phase 23B.5 — Reliability hardening tests.

D1A  options.py runtime execution (no NameError)
D1B  intelligence.py runtime execution (no NameError)
D2   Calendar provider → cache → fallback architecture
D3   Calendar source_meta transparency
D4   Previously unexecuted paths
D5   Tool health calendar integration
"""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from mcp.server.fastmcp import FastMCP as _FastMCP


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _opts_mcp():
    from src.tools import options
    mcp = _FastMCP("test")
    options.register(mcp)
    return {t.name: t for t in mcp._tool_manager.list_tools()}


def _intel_mcp():
    from src.tools import intelligence
    mcp = _FastMCP("test")
    intelligence.register(mcp)
    return {t.name: t for t in mcp._tool_manager.list_tools()}


def _meta_mcp():
    from src.tools import meta_tools
    mcp = _FastMCP("test")
    meta_tools.register(mcp)
    return {t.name: t for t in mcp._tool_manager.list_tools()}


_MOCK_CHAIN = {
    "records": {
        "underlyingValue": 24000.0,
        "expiryDates": ["26-Jun-2025", "03-Jul-2025"],
        "data": [
            {
                "strikePrice": 24000.0,
                "expiryDate": "26-Jun-2025",
                "CE": {"openInterest": 5000, "changeinOpenInterest": 100,
                       "totalTradedVolume": 2000, "impliedVolatility": 14.0,
                       "lastPrice": 150.0, "bidprice": 149.0, "askPrice": 151.0},
                "PE": {"openInterest": 4000, "changeinOpenInterest": -50,
                       "totalTradedVolume": 1500, "impliedVolatility": 15.0,
                       "lastPrice": 120.0, "bidprice": 119.0, "askPrice": 121.0},
            },
        ],
    }
}


# ---------------------------------------------------------------------------
# D1A — options.py runtime execution (no NameError)
# ---------------------------------------------------------------------------

class TestOptionsRuntimeExecution:
    """Verify that the MCP tool wrappers execute without NameError."""

    def _mock_svc(self):
        svc = MagicMock()
        svc.get_option_chain.return_value = _MOCK_CHAIN
        return svc

    def test_get_nifty_option_chain_executes(self):
        tools = _opts_mcp()
        svc = self._mock_svc()
        with patch("src.tools.options.get_options_service", return_value=svc):
            result = tools["get_nifty_option_chain"].fn(expiry="26-Jun-2025", atm_range=1)
        # No NameError → result must be a dict
        assert isinstance(result, dict)

    def test_get_nifty_option_chain_symbol_in_response(self):
        tools = _opts_mcp()
        svc = self._mock_svc()
        with patch("src.tools.options.get_options_service", return_value=svc):
            result = tools["get_nifty_option_chain"].fn(expiry="26-Jun-2025", atm_range=1)
        assert result.get("symbol") == "NIFTY"

    def test_get_banknifty_option_chain_executes(self):
        tools = _opts_mcp()
        svc = self._mock_svc()
        with patch("src.tools.options.get_options_service", return_value=svc):
            result = tools["get_banknifty_option_chain"].fn(expiry="26-Jun-2025", atm_range=1)
        assert isinstance(result, dict)

    def test_get_banknifty_option_chain_symbol_in_response(self):
        tools = _opts_mcp()
        svc = self._mock_svc()
        with patch("src.tools.options.get_options_service", return_value=svc):
            result = tools["get_banknifty_option_chain"].fn(expiry="26-Jun-2025", atm_range=1)
        assert result.get("symbol") == "BANKNIFTY"

    def test_get_equity_option_chain_executes(self):
        tools = _opts_mcp()
        svc = self._mock_svc()
        with patch("src.tools.options.get_options_service", return_value=svc):
            result = tools["get_equity_option_chain"].fn(
                symbol="INFY", expiry="26-Jun-2025", atm_range=1
            )
        assert isinstance(result, dict)

    def test_get_equity_option_chain_symbol_in_response(self):
        tools = _opts_mcp()
        svc = self._mock_svc()
        with patch("src.tools.options.get_options_service", return_value=svc):
            result = tools["get_equity_option_chain"].fn(
                symbol="INFY", expiry="26-Jun-2025", atm_range=1
            )
        assert result.get("symbol") == "INFY"

    def test_fetch_uses_symbol_parameter_not_free_variable(self):
        """Regression: _fetch must NOT reference nse_sym as a free variable."""
        import inspect
        from src.tools import options as opts_mod
        tools = _opts_mcp()
        # The real test: execution doesn't raise NameError.
        svc = self._mock_svc()
        with patch("src.tools.options.get_options_service", return_value=svc):
            r1 = tools["get_nifty_option_chain"].fn(atm_range=0)
            r2 = tools["get_banknifty_option_chain"].fn(atm_range=0)
        assert "symbol" in r1 and "symbol" in r2


# ---------------------------------------------------------------------------
# D1B — intelligence.py runtime execution (no NameError)
# ---------------------------------------------------------------------------

class TestIntelligenceRuntimeExecution:
    """Verify get_market_risk_score executes without NameError from missing _norm."""

    def test_get_market_risk_score_executes(self):
        tools = _intel_mcp()
        with patch("src.intelligence.risk.get_market_risk_score", return_value={
            "score": 35, "rating": "MODERATE", "factors": [], "recommendation": "ok",
            "inputs": {}
        }):
            result = tools["get_market_risk_score"].fn("NIFTY")
        assert isinstance(result, dict)

    def test_get_market_risk_score_no_name_error(self):
        """Regression: missing _norm import caused NameError."""
        tools = _intel_mcp()
        with patch("src.intelligence.risk.get_market_risk_score", return_value={
            "score": 35, "rating": "MODERATE", "factors": [], "recommendation": "ok",
            "inputs": {}
        }):
            # Must not raise NameError
            result = tools["get_market_risk_score"].fn("BANKNIFTY")
        assert "score" in result or "error" in result

    def test_get_market_risk_score_meta_present(self):
        """Meta must be set even though PASSTHROUGH format produces corrected=False."""
        tools = _intel_mcp()
        with patch("src.intelligence.risk.get_market_risk_score", return_value={
            "score": 40, "rating": "MODERATE", "factors": [], "recommendation": "ok",
            "inputs": {}
        }):
            result = tools["get_market_risk_score"].fn("NSE:INFY")
        # PASSTHROUGH → corrected=False, but meta must still be present
        assert "meta" in result
        assert "type" in result["meta"]

# ---------------------------------------------------------------------------
# D2 — Calendar provider → cache → fallback architecture
# ---------------------------------------------------------------------------

class TestCalendarHolidayArchitecture:
    """Test the three-tier holiday resolution architecture."""

    def setup_method(self):
        from src.market import calendar as _cal
        _cal._reset_holiday_cache()

    def teardown_method(self):
        from src.market import calendar as _cal
        _cal._reset_holiday_cache()

    def test_fallback_used_when_provider_returns_none(self):
        from src.market.calendar import _load_holidays, _NSE_HOLIDAYS_2026
        with patch("src.market.calendar._holiday_provider", return_value=None):
            holidays, source = _load_holidays()
        assert source == "not_configured"   # provider returned None → intentionally not configured
        assert holidays is _NSE_HOLIDAYS_2026

    def test_provider_data_used_when_available(self):
        custom = {date(2026, 3, 5): "Custom Holiday"}
        from src.market.calendar import _load_holidays
        with patch("src.market.calendar._holiday_provider", return_value=custom):
            holidays, source = _load_holidays()
        assert source == "provider"
        assert holidays is custom

    def test_cache_populated_from_provider(self):
        import src.market.calendar as _cal
        custom = {date(2026, 3, 5): "Custom Holiday"}
        with patch("src.market.calendar._holiday_provider", return_value=custom):
            _cal._load_holidays()
        assert _cal._holiday_cache is custom
        assert _cal._holiday_source == "provider"

    def test_provider_not_retried_after_first_load(self):
        """Provider should be called exactly once per session."""
        from src.market.calendar import _load_holidays
        call_count = 0

        def counting_provider():
            nonlocal call_count
            call_count += 1
            return None

        with patch("src.market.calendar._holiday_provider", side_effect=counting_provider):
            _load_holidays()
            _load_holidays()
            _load_holidays()
        assert call_count == 1

    def test_provider_exception_falls_back(self):
        from src.market.calendar import _load_holidays, _NSE_HOLIDAYS_2026
        with patch("src.market.calendar._holiday_provider", side_effect=RuntimeError("network")):
            holidays, source = _load_holidays()
        assert source == "offline"          # provider raised → configured but unavailable
        assert holidays is _NSE_HOLIDAYS_2026

    def test_cache_source_when_provider_pre_populated(self):
        """If cache is already populated (by a prior provider call), source is 'cache'."""
        import src.market.calendar as _cal
        # Simulate cache already populated by a prior provider call
        _cal._holiday_cache = {date(2026, 4, 1): "Test"}
        _cal._holidays_loaded = True
        _cal._holiday_source = "cache"
        _, source = _cal._load_holidays()
        assert source == "cache"

    def test_reset_clears_all_state(self):
        import src.market.calendar as _cal
        _cal._holiday_cache = {date(2026, 1, 1): "Test"}
        _cal._holidays_loaded = True
        _cal._holiday_source = "provider"
        _cal._reset_holiday_cache()
        assert _cal._holiday_cache is None
        assert _cal._holidays_loaded is False
        assert _cal._holiday_source == "not_configured"


# ---------------------------------------------------------------------------
# D3 — Calendar source_meta transparency
# ---------------------------------------------------------------------------

class TestCalendarSourceMeta:
    def setup_method(self):
        from src.market import calendar as _cal
        _cal._reset_holiday_cache()

    def teardown_method(self):
        from src.market import calendar as _cal
        _cal._reset_holiday_cache()

    def test_source_meta_present_in_calendar(self):
        with patch("src.market.calendar._live_expiries", return_value={}):
            from src.market.calendar import get_market_calendar
            cal = get_market_calendar()
        assert "source_meta" in cal

    def test_source_meta_has_holiday_source(self):
        with patch("src.market.calendar._live_expiries", return_value={}):
            from src.market.calendar import get_market_calendar
            cal = get_market_calendar()
        assert "holiday_source" in cal["source_meta"]

    def test_source_meta_has_expiry_source(self):
        with patch("src.market.calendar._live_expiries", return_value={}):
            from src.market.calendar import get_market_calendar
            cal = get_market_calendar()
        assert "expiry_source" in cal["source_meta"]

    def test_expiry_source_live_when_nse_reachable(self):
        mock_live = {"nifty": "26-Jun-2025", "banknifty": "25-Jun-2025"}
        with patch("src.market.calendar._live_expiries", return_value=mock_live):
            from src.market.calendar import get_market_calendar
            cal = get_market_calendar()
        assert cal["source_meta"]["expiry_source"] == "live"

    def test_expiry_source_algorithmic_when_nse_unreachable(self):
        with patch("src.market.calendar._live_expiries", return_value={}):
            from src.market.calendar import get_market_calendar
            cal = get_market_calendar()
        assert cal["source_meta"]["expiry_source"] == "algorithmic"

    def test_holiday_source_not_configured_when_no_provider(self):
        with patch("src.market.calendar._holiday_provider", return_value=None):
            with patch("src.market.calendar._live_expiries", return_value={}):
                from src.market.calendar import get_market_calendar
                cal = get_market_calendar()
        assert cal["source_meta"]["holiday_source"] == "not_configured"

    def test_holiday_source_provider_when_provider_returns_data(self):
        custom = {date(2026, 5, 1): "Test Holiday"}
        with patch("src.market.calendar._holiday_provider", return_value=custom):
            with patch("src.market.calendar._live_expiries", return_value={}):
                from src.market.calendar import get_market_calendar
                cal = get_market_calendar()
        assert cal["source_meta"]["holiday_source"] == "provider"

    def test_source_meta_propagates_to_mcp_wrapper(self):
        """MCP wrapper must expose source_meta inside data."""
        tools = _meta_mcp()
        fn = tools["get_market_calendar"].fn
        with patch("src.market.calendar._live_expiries", return_value={}):
            result = fn()
        assert "source_meta" in result["data"]


# ---------------------------------------------------------------------------
# D4 — Previously unexecuted paths
# ---------------------------------------------------------------------------

class TestCalendarExpiredHolidayAdjustment:
    """Test that expiry falling on holiday rolls back to preceding trading day."""

    def setup_method(self):
        from src.market import calendar as _cal
        _cal._reset_holiday_cache()

    def teardown_method(self):
        from src.market import calendar as _cal
        _cal._reset_holiday_cache()

    def test_expiry_rolls_back_on_holiday(self):
        """If computed Thursday is a holiday, expiry becomes Wednesday."""
        from src.market.calendar import _nearest_expiry_algorithmic

        # Find the next Thursday
        today = date(2026, 6, 22)  # Monday
        next_thu = date(2026, 6, 25)  # Thursday

        # Make Thursday a holiday
        mock_holidays = {next_thu: "Test Holiday"}
        with patch("src.market.calendar._load_holidays", return_value=(mock_holidays, "provider")):
            result = _nearest_expiry_algorithmic("nifty", today)

        assert result is not None
        assert result < next_thu  # must be before the holiday

    def test_expiry_rolls_back_on_weekend(self):
        """Algorithmic expiry must not fall on a Saturday or Sunday."""
        from src.market.calendar import _nearest_expiry_algorithmic

        with patch("src.market.calendar._load_holidays", return_value=({}, "fallback")):
            # Use a date where we can predict the result
            result = _nearest_expiry_algorithmic("nifty", date(2026, 6, 22))
        if result:
            assert result.weekday() < 5  # must be a weekday

    def test_next_trading_day_skips_weekend(self):
        from src.market.calendar import _next_trading_day
        friday = date(2026, 6, 19)  # Friday
        with patch("src.market.calendar._load_holidays", return_value=({}, "fallback")):
            nxt = _next_trading_day(friday)
        assert nxt.weekday() == 0  # Monday

    def test_next_trading_day_skips_holiday(self):
        from src.market.calendar import _next_trading_day
        monday = date(2026, 6, 22)
        tuesday = date(2026, 6, 23)
        wednesday = date(2026, 6, 24)
        # Make Tuesday a holiday
        with patch("src.market.calendar._load_holidays",
                   return_value=({tuesday: "Test"}, "provider")):
            nxt = _next_trading_day(monday)
        assert nxt == wednesday

    def test_is_holiday_false_for_non_holiday(self):
        from src.market.calendar import _is_holiday
        from src.market import calendar as _cal
        _cal._reset_holiday_cache()
        with patch("src.market.calendar._holiday_provider", return_value={}):
            assert not _is_holiday(date(2026, 6, 22))

    def test_upcoming_holidays_returns_list(self):
        from src.market.calendar import _upcoming_holidays
        from src.market import calendar as _cal
        _cal._reset_holiday_cache()
        with patch("src.market.calendar._holiday_provider", return_value=None):
            result = _upcoming_holidays(date(2026, 6, 1), days_ahead=60)
        assert isinstance(result, list)

    def test_upcoming_holidays_within_window(self):
        from src.market.calendar import _upcoming_holidays
        custom = {date(2026, 6, 25): "Test Holiday"}
        with patch("src.market.calendar._load_holidays", return_value=(custom, "provider")):
            result = _upcoming_holidays(date(2026, 6, 20), days_ahead=10)
        assert len(result) == 1
        assert result[0]["date"] == "2026-06-25"

    def test_upcoming_holidays_excludes_past(self):
        from src.market.calendar import _upcoming_holidays
        custom = {date(2026, 6, 15): "Past Holiday", date(2026, 6, 25): "Future Holiday"}
        with patch("src.market.calendar._load_holidays", return_value=(custom, "provider")):
            result = _upcoming_holidays(date(2026, 6, 20), days_ahead=10)
        dates = [r["date"] for r in result]
        assert "2026-06-15" not in dates
        assert "2026-06-25" in dates


# ---------------------------------------------------------------------------
# D5 — Tool health calendar integration
# ---------------------------------------------------------------------------

class TestToolHealthCalendarIntegration:
    def setup_method(self):
        from src.market import calendar as _cal
        _cal._reset_holiday_cache()

    def teardown_method(self):
        from src.market import calendar as _cal
        _cal._reset_holiday_cache()

    def _get_health(self):
        tools = _meta_mcp()
        return tools["get_tool_health"].fn()

    def test_get_market_calendar_in_tools(self):
        result = self._get_health()
        assert "get_market_calendar" in result["data"]["tools"]

    def test_calendar_tool_has_holiday_source(self):
        result = self._get_health()
        cal_entry = result["data"]["tools"]["get_market_calendar"]
        assert "holiday_source" in cal_entry

    def test_calendar_tool_has_expiry_source(self):
        result = self._get_health()
        cal_entry = result["data"]["tools"]["get_market_calendar"]
        assert "expiry_source" in cal_entry

    def test_calendar_not_degraded_when_not_configured(self):
        """No provider configured → CONFIGURATION_LIMITED → tool status stays healthy."""
        with patch("src.market.calendar._holiday_provider", return_value=None):
            result = self._get_health()
        cal_entry = result["data"]["tools"]["get_market_calendar"]
        # not_configured → CONFIGURATION_LIMITED → NOT degraded (system functioning normally)
        assert cal_entry["status"] == "healthy"
        assert cal_entry["holiday_source"] == "not_configured"
        assert cal_entry["calendar_status"] == "CONFIGURATION_LIMITED"

    def test_calendar_healthy_when_provider_active(self):
        """When provider returns data, calendar is healthy (expiry source is irrelevant)."""
        custom = {date(2026, 12, 25): "Christmas"}
        with patch("src.market.calendar._holiday_provider", return_value=custom):
            result = self._get_health()
        cal_entry = result["data"]["tools"]["get_market_calendar"]
        assert cal_entry["status"] == "healthy"
        assert cal_entry["holiday_source"] == "provider"

    def test_degraded_count_increases_when_provider_offline(self):
        """Provider raising an exception → OFFLINE → calendar counts as degraded."""
        with patch("src.market.calendar._holiday_provider", side_effect=RuntimeError("down")):
            result = self._get_health()
        summary = result["data"]["summary"]
        assert summary["degraded"] >= 1

    def test_tool_health_has_reason_when_degraded(self):
        """When provider is offline (exception), entry has a non-empty reason."""
        with patch("src.market.calendar._holiday_provider", side_effect=RuntimeError("down")):
            result = self._get_health()
        cal_entry = result["data"]["tools"]["get_market_calendar"]
        assert cal_entry["status"] == "degraded"
        assert "reason" in cal_entry
        assert cal_entry["reason"]


# ---------------------------------------------------------------------------
# Backward-compatibility checks
# ---------------------------------------------------------------------------

class TestCalendarBackwardCompatibility:
    def setup_method(self):
        from src.market import calendar as _cal
        _cal._reset_holiday_cache()

    def teardown_method(self):
        from src.market import calendar as _cal
        _cal._reset_holiday_cache()

    def test_existing_sprint1_keys_still_present(self):
        """Sprint 1 test keys must still be present after calendar rewrite."""
        with patch("src.market.calendar._live_expiries", return_value={}):
            from src.market.calendar import get_market_calendar
            cal = get_market_calendar()
        required = {"today", "expiries", "days_to_expiry",
                    "upcoming_holidays", "next_trading_day", "week_summary"}
        assert required <= cal.keys()

    def test_today_keys_intact(self):
        with patch("src.market.calendar._live_expiries", return_value={}):
            from src.market.calendar import get_market_calendar
            cal = get_market_calendar()
        today = cal["today"]
        assert {"date", "day", "is_trading_day", "is_holiday"} <= today.keys()

    def test_week_summary_keys_intact(self):
        with patch("src.market.calendar._live_expiries", return_value={}):
            from src.market.calendar import get_market_calendar
            cal = get_market_calendar()
        ws = cal["week_summary"]
        assert "trading_days_remaining" in ws
        assert "expiry_days_this_week" in ws

    def test_live_expiries_attribute_still_present(self):
        """Sprint 1 test: from src.market import calendar; hasattr(calendar, '_live_expiries')"""
        from src.market import calendar as cal_mod
        assert hasattr(cal_mod, "_live_expiries")

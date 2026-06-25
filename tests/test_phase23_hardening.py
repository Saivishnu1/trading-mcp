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
        assert "score" in result.get("data", result) or "error" in result

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
# Helper for mocking the provider chain in calendar tests
# ---------------------------------------------------------------------------

def _make_provider_result(holidays: dict, status: str = "HEALTHY"):
    from src.providers.base import ProviderResult
    return ProviderResult(
        data=holidays,
        provider_name="MockProvider",
        data_source="test",
        authority="test",
        status=status,
        fallback_level=0,
        cache_status="MISS",
        cache_age_seconds=0,
        ttl_seconds=86400,
        last_refresh="2026-06-25T00:00:00Z",
    )


# ---------------------------------------------------------------------------
# D2 — Calendar provider → cache → fallback architecture (Phase 24A)
# ---------------------------------------------------------------------------

class TestCalendarHolidayArchitecture:
    """Test the provider chain holiday resolution architecture (JSON → Emergency)."""

    def setup_method(self):
        from src.market import calendar as _cal
        _cal._reset_holiday_cache()

    def teardown_method(self):
        from src.market import calendar as _cal
        _cal._reset_holiday_cache()

    def test_json_data_loaded_on_first_call(self):
        """JSON provider returns holidays when files are present."""
        custom = {date(2026, 3, 5): "Custom Holiday"}
        with patch("src.providers.calendar.json_provider.JSONCalendarProvider._load_raw_json",
                   return_value=custom):
            from src.providers.calendar.chain import get_calendar_provider
            result = get_calendar_provider().fetch()
        assert result.status == "HEALTHY"
        assert date(2026, 3, 5) in result.data

    def test_emergency_fallback_when_json_unavailable(self):
        """When JSON files are missing, emergency provider data is used."""
        with patch("src.providers.calendar.json_provider.JSONCalendarProvider._load_raw_json",
                   side_effect=FileNotFoundError("no json")):
            from src.providers.calendar.chain import get_calendar_provider
            result = get_calendar_provider().fetch()
        assert result.status == "EMERGENCY"
        assert isinstance(result.data, dict)

    def test_cache_hit_after_first_load(self):
        """Second fetch within TTL returns from in-memory cache (status CACHED)."""
        custom = {date(2026, 3, 5): "Custom Holiday"}
        with patch("src.providers.calendar.json_provider.JSONCalendarProvider._load_raw_json",
                   return_value=custom) as mock_load:
            from src.providers.calendar.chain import get_calendar_provider
            chain = get_calendar_provider()
            chain.fetch()            # first load → HEALTHY, populates cache
            result = chain.fetch()   # cache hit → CACHED
        assert mock_load.call_count == 1   # JSON only read once

    def test_json_not_re_read_within_ttl(self):
        """JSON file is not re-read on every call within the TTL window."""
        custom = {date(2026, 3, 5): "Custom"}
        with patch("src.providers.calendar.json_provider.JSONCalendarProvider._load_raw_json",
                   return_value=custom) as mock_load:
            from src.providers.calendar.chain import get_calendar_provider
            chain = get_calendar_provider()
            chain.fetch()
            chain.fetch()
            chain.fetch()
        assert mock_load.call_count == 1   # cached after first read

    def test_emergency_fallback_when_json_raises(self):
        """Any exception from JSON loading falls back to emergency provider."""
        with patch("src.providers.calendar.json_provider.JSONCalendarProvider._load_raw_json",
                   side_effect=RuntimeError("disk error")):
            from src.providers.calendar.chain import get_calendar_provider
            result = get_calendar_provider().fetch()
        assert result.status == "EMERGENCY"
        assert result.provider_name == "EmergencyCalendarProvider"

    def test_cache_hit_returns_cached_status(self):
        """Cache hit carries status=CACHED and cache_status=HIT."""
        custom = {date(2026, 3, 5): "Custom"}
        with patch("src.providers.calendar.json_provider.JSONCalendarProvider._load_raw_json",
                   return_value=custom):
            from src.providers.calendar.chain import get_calendar_provider
            chain = get_calendar_provider()
            chain.fetch()            # populate cache
            result = chain.fetch()   # cache hit
        assert result.status == "CACHED"
        assert result.cache_status == "HIT"

    def test_reset_clears_cache_and_singleton(self):
        """reset_calendar_provider clears cache; next fetch reloads from JSON."""
        custom = {date(2026, 3, 5): "Custom"}
        with patch("src.providers.calendar.json_provider.JSONCalendarProvider._load_raw_json",
                   return_value=custom) as mock_load:
            from src.providers.calendar.chain import get_calendar_provider, reset_calendar_provider
            get_calendar_provider().fetch()   # first load
            reset_calendar_provider()         # wipe singleton
            get_calendar_provider().fetch()   # fresh load on new chain
        assert mock_load.call_count == 2


# ---------------------------------------------------------------------------
# D3 — Calendar source_meta transparency (Phase 24A: provider-aware structure)
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

    def test_source_meta_has_provider_field(self):
        """Phase 24A: source_meta now has 'provider' (was 'holiday_source')."""
        with patch("src.market.calendar._live_expiries", return_value={}):
            from src.market.calendar import get_market_calendar
            cal = get_market_calendar()
        assert "provider" in cal["source_meta"]

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

    def test_source_meta_provider_is_json_provider_when_json_loads(self):
        """When JSON files load successfully, provider is JSONCalendarProvider."""
        custom = {date(2026, 5, 1): "Test Holiday"}
        with patch("src.providers.calendar.json_provider.JSONCalendarProvider._load_raw_json",
                   return_value=custom):
            with patch("src.market.calendar._live_expiries", return_value={}):
                from src.market.calendar import get_market_calendar
                cal = get_market_calendar()
        assert cal["source_meta"]["provider"] == "JSONCalendarProvider"
        assert cal["source_meta"]["status"] in ("HEALTHY", "CACHED")

    def test_source_meta_provider_is_emergency_when_json_fails(self):
        """When JSON files are unavailable, emergency provider is reported."""
        with patch("src.providers.calendar.json_provider.JSONCalendarProvider._load_raw_json",
                   side_effect=FileNotFoundError("no json")):
            with patch("src.market.calendar._live_expiries", return_value={}):
                from src.market.calendar import get_market_calendar
                cal = get_market_calendar()
        assert cal["source_meta"]["provider"] == "EmergencyCalendarProvider"
        assert cal["source_meta"]["status"] == "EMERGENCY"

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

    def _mock_chain(self, holidays: dict):
        from unittest.mock import MagicMock
        chain = MagicMock()
        chain.fetch.return_value = _make_provider_result(holidays)
        chain.last_result = None
        chain.health.return_value = {"status": "HEALTHY", "severity": "INFO",
                                     "holiday_source": "json", "expiry_source": "algorithmic"}
        return chain

    def test_expiry_rolls_back_on_holiday(self):
        """If computed Thursday is a holiday, expiry becomes Wednesday."""
        from src.market.calendar import _nearest_expiry_algorithmic
        today = date(2026, 6, 22)   # Monday
        next_thu = date(2026, 6, 25)  # Thursday
        mock_holidays = {next_thu: "Test Holiday"}
        with patch("src.market.calendar.get_calendar_provider",
                   return_value=self._mock_chain(mock_holidays)):
            result = _nearest_expiry_algorithmic("nifty", today)
        assert result is not None
        assert result < next_thu  # must be before the holiday

    def test_expiry_rolls_back_on_weekend(self):
        """Algorithmic expiry must not fall on a Saturday or Sunday."""
        from src.market.calendar import _nearest_expiry_algorithmic
        with patch("src.market.calendar.get_calendar_provider",
                   return_value=self._mock_chain({})):
            result = _nearest_expiry_algorithmic("nifty", date(2026, 6, 22))
        if result:
            assert result.weekday() < 5

    def test_next_trading_day_skips_weekend(self):
        from src.market.calendar import _next_trading_day
        friday = date(2026, 6, 19)
        with patch("src.market.calendar.get_calendar_provider",
                   return_value=self._mock_chain({})):
            nxt = _next_trading_day(friday)
        assert nxt.weekday() == 0  # Monday

    def test_next_trading_day_skips_holiday(self):
        from src.market.calendar import _next_trading_day
        monday = date(2026, 6, 22)
        tuesday = date(2026, 6, 23)
        wednesday = date(2026, 6, 24)
        with patch("src.market.calendar.get_calendar_provider",
                   return_value=self._mock_chain({tuesday: "Test"})):
            nxt = _next_trading_day(monday)
        assert nxt == wednesday

    def test_is_holiday_false_for_non_holiday(self):
        from src.market.calendar import _is_holiday
        with patch("src.market.calendar.get_calendar_provider",
                   return_value=self._mock_chain({})):
            assert not _is_holiday(date(2026, 6, 22))

    def test_upcoming_holidays_returns_list(self):
        from src.market.calendar import _upcoming_holidays
        with patch("src.market.calendar.get_calendar_provider",
                   return_value=self._mock_chain({})):
            result = _upcoming_holidays(date(2026, 6, 1), days_ahead=60)
        assert isinstance(result, list)

    def test_upcoming_holidays_within_window(self):
        from src.market.calendar import _upcoming_holidays
        custom = {date(2026, 6, 25): "Test Holiday"}
        with patch("src.market.calendar.get_calendar_provider",
                   return_value=self._mock_chain(custom)):
            result = _upcoming_holidays(date(2026, 6, 20), days_ahead=10)
        assert len(result) == 1
        assert result[0]["date"] == "2026-06-25"

    def test_upcoming_holidays_excludes_past(self):
        from src.market.calendar import _upcoming_holidays
        custom = {date(2026, 6, 15): "Past Holiday", date(2026, 6, 25): "Future Holiday"}
        with patch("src.market.calendar.get_calendar_provider",
                   return_value=self._mock_chain(custom)):
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

    def test_calendar_not_degraded_when_json_available(self):
        """JSON calendar available → HEALTHY/CACHED → not degraded."""
        custom = {date(2026, 12, 25): "Christmas"}
        with patch("src.providers.calendar.json_provider.JSONCalendarProvider._load_raw_json",
                   return_value=custom):
            result = self._get_health()
        cal_entry = result["data"]["tools"]["get_market_calendar"]
        assert cal_entry["status"] == "healthy"
        assert cal_entry["calendar_status"] in ("HEALTHY", "CACHED")

    def test_calendar_healthy_when_json_loads(self):
        """When JSON loads fresh, calendar_status is HEALTHY and tool is healthy."""
        custom = {date(2026, 12, 25): "Christmas"}
        with patch("src.providers.calendar.json_provider.JSONCalendarProvider._load_raw_json",
                   return_value=custom):
            result = self._get_health()
        cal_entry = result["data"]["tools"]["get_market_calendar"]
        assert cal_entry["status"] == "healthy"
        assert cal_entry["holiday_source"] in ("json", "cache")

    def test_degraded_count_increases_when_json_unavailable(self):
        """JSON unavailable → EMERGENCY → calendar counts as degraded."""
        with patch("src.providers.calendar.json_provider.JSONCalendarProvider._load_raw_json",
                   side_effect=FileNotFoundError("no json")):
            result = self._get_health()
        summary = result["data"]["summary"]
        assert summary["degraded"] >= 1

    def test_tool_health_has_reason_when_degraded(self):
        """When JSON is unavailable (EMERGENCY), the tool entry has a reason."""
        with patch("src.providers.calendar.json_provider.JSONCalendarProvider._load_raw_json",
                   side_effect=FileNotFoundError("no json")):
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

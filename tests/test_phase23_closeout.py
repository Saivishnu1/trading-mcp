"""
Phase 23B.6 — Architectural Closeout tests.

D1  Intelligence symbol normalization — all tools have documented format
D2  Calendar health semantics — CONFIGURATION_LIMITED vs DEGRADED
D3  Tool health contract — reason/severity/recommended_action per status
D4  Error contract consistency — status/tool/reason/suggestions/alternative
D5  Metadata consistency — all intelligence MCP tools wrapped
D6  Calendar source transparency — source names correct
"""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from mcp.server.fastmcp import FastMCP as _FastMCP


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _tech_mcp():
    from src.tools import technicals
    mcp = _FastMCP("test")
    technicals.register(mcp)
    return {t.name: t for t in mcp._tool_manager.list_tools()}


def _analysis_mcp():
    from src.tools import analysis
    mcp = _FastMCP("test")
    analysis.register(mcp)
    return {t.name: t for t in mcp._tool_manager.list_tools()}


# ---------------------------------------------------------------------------
# D1 — Intelligence symbol normalization
# ---------------------------------------------------------------------------

class TestIntelligenceSymbolNormalization:
    """Every intelligence tool must have a documented, verifiable normalization policy."""

    def test_get_market_risk_score_format_is_passthrough(self):
        """PASSTHROUGH is correct: downstream PCR (NSELive) needs bare 'NIFTY', not '^NSEI'."""
        from src.market.symbols import normalize_symbol_extended
        _, _, fmt = normalize_symbol_extended("INFY", "get_market_risk_score")
        assert fmt == "PASSTHROUGH"

    def test_get_market_risk_score_passthrough_preserves_symbol(self):
        from src.market.symbols import normalize_symbol_extended
        sym, corrected, _ = normalize_symbol_extended("INFY", "get_market_risk_score")
        assert sym == "INFY"
        assert corrected is False

    def test_get_market_risk_score_index_uses_canonical(self):
        """Index names trigger INDEX_CANONICAL regardless of tool format — documented behaviour."""
        from src.market.symbols import normalize_symbol_extended
        sym, _, fmt = normalize_symbol_extended("NIFTY", "get_market_risk_score")
        # Index aliases always resolve via INDEX_CANONICAL (yfinance ticker)
        assert fmt == "INDEX_CANONICAL"
        assert sym == "^NSEI"

    def test_get_regime_alignment_format_is_bare(self):
        from src.market.symbols import normalize_symbol_extended
        _, _, fmt = normalize_symbol_extended("NSE:INFY", "get_regime_alignment")
        assert fmt == "BARE"

    def test_get_regime_alignment_strips_nse_prefix(self):
        from src.market.symbols import normalize_symbol_extended
        sym, corrected, _ = normalize_symbol_extended("NSE:INFY", "get_regime_alignment")
        assert sym == "INFY"
        assert corrected is True

    def test_detect_market_regime_and_regime_alignment_same_format(self):
        """get_regime_alignment and detect_market_regime must use the same format."""
        from src.market.symbols import normalize_symbol_extended
        sym_dm, _, fmt_dm = normalize_symbol_extended("NSE:INFY", "detect_market_regime")
        sym_ra, _, fmt_ra = normalize_symbol_extended("NSE:INFY", "get_regime_alignment")
        assert fmt_dm == fmt_ra
        assert sym_dm == sym_ra

    def test_calculate_macd_format_is_yf_ns(self):
        from src.market.symbols import normalize_symbol_extended
        _, _, fmt = normalize_symbol_extended("INFY", "calculate_macd")
        assert fmt == "YF_NS_SUFFIX"

    def test_calculate_macd_adds_ns_suffix(self):
        from src.market.symbols import normalize_symbol_extended
        sym, corrected, _ = normalize_symbol_extended("INFY", "calculate_macd")
        assert sym == "INFY.NS"
        assert corrected is True

    def test_calculate_atr_format_is_yf_ns(self):
        from src.market.symbols import normalize_symbol_extended
        _, _, fmt = normalize_symbol_extended("INFY", "calculate_atr")
        assert fmt == "YF_NS_SUFFIX"

    def test_calculate_atr_adds_ns_suffix(self):
        from src.market.symbols import normalize_symbol_extended
        sym, corrected, _ = normalize_symbol_extended("INFY", "calculate_atr")
        assert sym == "INFY.NS"
        assert corrected is True

    def test_calculate_macd_consistent_with_calculate_rsi(self):
        """MACD and RSI now use identical format."""
        from src.market.symbols import normalize_symbol_extended
        _, _, fmt_macd = normalize_symbol_extended("INFY", "calculate_macd")
        _, _, fmt_rsi = normalize_symbol_extended("INFY", "calculate_rsi")
        assert fmt_macd == fmt_rsi

    def test_calculate_atr_consistent_with_calculate_adx(self):
        """ATR and ADX now use identical format."""
        from src.market.symbols import normalize_symbol_extended
        _, _, fmt_atr = normalize_symbol_extended("INFY", "calculate_atr")
        _, _, fmt_adx = normalize_symbol_extended("INFY", "calculate_adx")
        assert fmt_atr == fmt_adx

    def test_options_tools_passthrough_documented(self):
        """NSELive options tools intentionally use PASSTHROUGH — verify with equity symbol.

        Note: index symbols (NIFTY, BANKNIFTY) trigger INDEX_CANONICAL before the
        PASSTHROUGH path. PASSTHROUGH is verified here with an equity symbol ('INFY').
        """
        from src.market.symbols import normalize_symbol_extended
        for tool in ("get_expiries", "get_equity_option_chain", "calculate_pcr",
                     "get_oi_analysis", "calculate_max_pain", "get_option_chain_depth"):
            _, _, fmt = normalize_symbol_extended("INFY", tool)
            assert fmt == "PASSTHROUGH", f"{tool} expected PASSTHROUGH, got {fmt}"

    def test_catalyst_tools_passthrough_documented(self):
        """Catalyst tools intentionally use PASSTHROUGH — service layer handles resolution."""
        from src.market.symbols import normalize_symbol_extended
        for tool in ("get_symbol_news", "get_news_sentiment",
                     "get_earnings_calendar", "get_event_risk"):
            _, _, fmt = normalize_symbol_extended("INFY", tool)
            assert fmt == "PASSTHROUGH", f"{tool} expected PASSTHROUGH, got {fmt}"

    def test_intelligence_risk_passthrough_documented(self):
        """get_market_risk_score uses PASSTHROUGH — PCR requires bare NSE names."""
        from src.market.symbols import normalize_symbol_extended
        _, _, fmt = normalize_symbol_extended("INFY", "get_market_risk_score")
        assert fmt == "PASSTHROUGH"


# ---------------------------------------------------------------------------
# D2 — Calendar health semantics
# ---------------------------------------------------------------------------

class TestCalendarHealthSemantics:
    def setup_method(self):
        from src.market import calendar as _cal
        _cal._reset_holiday_cache()

    def teardown_method(self):
        from src.market import calendar as _cal
        _cal._reset_holiday_cache()

    def test_healthy_when_provider_responds(self):
        from src.market.calendar import get_calendar_health
        custom = {date(2026, 12, 25): "Christmas"}
        with patch("src.market.calendar._holiday_provider", return_value=custom):
            h = get_calendar_health()
        assert h["status"] == "HEALTHY"

    def test_configuration_limited_when_not_configured(self):
        """Provider returning None = intentionally not configured — not an error."""
        from src.market.calendar import get_calendar_health
        with patch("src.market.calendar._holiday_provider", return_value=None):
            h = get_calendar_health()
        assert h["status"] == "CONFIGURATION_LIMITED"

    def test_configuration_limited_is_info_severity(self):
        from src.market.calendar import get_calendar_health
        with patch("src.market.calendar._holiday_provider", return_value=None):
            h = get_calendar_health()
        assert h["severity"] == "INFO"

    def test_offline_when_provider_raises(self):
        from src.market.calendar import get_calendar_health
        with patch("src.market.calendar._holiday_provider", side_effect=RuntimeError("net")):
            h = get_calendar_health()
        assert h["status"] == "OFFLINE"

    def test_offline_is_warning_severity(self):
        from src.market.calendar import get_calendar_health
        with patch("src.market.calendar._holiday_provider", side_effect=RuntimeError("net")):
            h = get_calendar_health()
        assert h["severity"] == "WARNING"

    def test_cached_when_cache_pre_populated(self):
        import src.market.calendar as _cal
        from src.market.calendar import get_calendar_health
        # Simulate cache already loaded from a prior provider call
        _cal._holiday_cache = {date(2026, 4, 1): "Test"}
        _cal._holidays_loaded = True
        _cal._holiday_source = "cache"
        h = get_calendar_health()
        assert h["status"] == "CACHED"

    def test_healthy_has_no_reason(self):
        from src.market.calendar import get_calendar_health
        custom = {date(2026, 12, 25): "Christmas"}
        with patch("src.market.calendar._holiday_provider", return_value=custom):
            h = get_calendar_health()
        assert "reason" not in h

    def test_configuration_limited_has_reason(self):
        from src.market.calendar import get_calendar_health
        with patch("src.market.calendar._holiday_provider", return_value=None):
            h = get_calendar_health()
        assert "reason" in h
        assert h["reason"]

    def test_configuration_limited_has_recommended_action(self):
        from src.market.calendar import get_calendar_health
        with patch("src.market.calendar._holiday_provider", return_value=None):
            h = get_calendar_health()
        assert "recommended_action" in h

    def test_offline_has_reason(self):
        from src.market.calendar import get_calendar_health
        with patch("src.market.calendar._holiday_provider", side_effect=RuntimeError("net")):
            h = get_calendar_health()
        assert "reason" in h


# ---------------------------------------------------------------------------
# D2 — Tool health integration with new calendar status
# ---------------------------------------------------------------------------

class TestToolHealthCalendarStatusIntegration:
    def setup_method(self):
        from src.market import calendar as _cal
        _cal._reset_holiday_cache()

    def teardown_method(self):
        from src.market import calendar as _cal
        _cal._reset_holiday_cache()

    def _get_health(self):
        tools = _meta_mcp()
        return tools["get_tool_health"].fn()

    def test_calendar_entry_has_calendar_status_field(self):
        result = self._get_health()
        assert "calendar_status" in result["data"]["tools"]["get_market_calendar"]

    def test_configuration_limited_not_counted_as_degraded(self):
        """CONFIGURATION_LIMITED is normal — must not inflate the degraded counter."""
        with patch("src.market.calendar._holiday_provider", return_value=None):
            result = self._get_health()
        summary = result["data"]["summary"]
        cal_entry = result["data"]["tools"]["get_market_calendar"]
        assert cal_entry["calendar_status"] == "CONFIGURATION_LIMITED"
        assert cal_entry["status"] == "healthy"
        assert summary["degraded"] == 0

    def test_offline_counted_as_degraded(self):
        """Provider offline → OFFLINE → degraded in summary."""
        with patch("src.market.calendar._holiday_provider", side_effect=RuntimeError("net")):
            result = self._get_health()
        summary = result["data"]["summary"]
        cal_entry = result["data"]["tools"]["get_market_calendar"]
        assert cal_entry["calendar_status"] == "OFFLINE"
        assert cal_entry["status"] == "degraded"
        assert summary["degraded"] >= 1

    def test_provider_active_calendar_healthy(self):
        custom = {date(2026, 12, 25): "Test"}
        with patch("src.market.calendar._holiday_provider", return_value=custom):
            result = self._get_health()
        cal_entry = result["data"]["tools"]["get_market_calendar"]
        assert cal_entry["calendar_status"] == "HEALTHY"
        assert cal_entry["status"] == "healthy"


# ---------------------------------------------------------------------------
# D3 — Tool health contract audit
# ---------------------------------------------------------------------------

class TestToolHealthContract:
    def setup_method(self):
        from src.market import calendar as _cal
        _cal._reset_holiday_cache()

    def teardown_method(self):
        from src.market import calendar as _cal
        _cal._reset_holiday_cache()

    def _all_tool_entries(self):
        tools = _meta_mcp()
        result = tools["get_tool_health"].fn()
        return result["data"]["tools"]

    def test_every_tool_has_status(self):
        for name, entry in self._all_tool_entries().items():
            assert "status" in entry, f"{name} missing status"

    def test_every_tool_has_severity(self):
        for name, entry in self._all_tool_entries().items():
            assert "severity" in entry, f"{name} missing severity"

    def test_every_tool_has_data_lag(self):
        for name, entry in self._all_tool_entries().items():
            assert "data_lag" in entry, f"{name} missing data_lag"

    def test_time_gated_tools_have_reason(self):
        entries = self._all_tool_entries()
        from src.tools.meta_tools import _TIME_GATED
        for name in _TIME_GATED:
            if name in entries:
                assert "reason" in entries[name], f"{name} time_gated missing reason"

    def test_time_gated_tools_have_recommended_action(self):
        entries = self._all_tool_entries()
        from src.tools.meta_tools import _TIME_GATED
        for name in _TIME_GATED:
            if name in entries:
                assert "recommended_action" in entries[name], f"{name} time_gated missing recommended_action"

    def test_time_gated_severity_is_info(self):
        entries = self._all_tool_entries()
        from src.tools.meta_tools import _TIME_GATED
        for name in _TIME_GATED:
            if name in entries:
                assert entries[name]["severity"] == "INFO", f"{name} time_gated should be INFO"

    def test_healthy_severity_is_info(self):
        entries = self._all_tool_entries()
        for name, entry in entries.items():
            if entry["status"] == "healthy":
                assert entry["severity"] == "INFO", f"{name} healthy should be INFO"

    def test_healthy_tools_no_spurious_reason(self):
        """Healthy tools that are also HEALTHY for calendar must not have a spurious reason field."""
        with patch("src.market.calendar._holiday_provider", return_value={date(2026, 12, 25): "X"}):
            tools = _meta_mcp()
            result = tools["get_tool_health"].fn()
        for name, entry in result["data"]["tools"].items():
            if entry["status"] == "healthy" and name != "get_market_calendar":
                assert "reason" not in entry, f"healthy tool {name} must not have reason"


# ---------------------------------------------------------------------------
# D4 — Error contract consistency
# ---------------------------------------------------------------------------

class TestErrorContractConsistency:

    def test_symbol_error_has_required_keys(self):
        from src import meta as _meta
        err = _meta.make_symbol_error("", "some_tool")
        for key in ("status", "tool", "reason", "suggestions", "alternative"):
            assert key in err, f"make_symbol_error missing: {key}"

    def test_symbol_error_status_value(self):
        from src import meta as _meta
        err = _meta.make_symbol_error("", "t")
        assert err["status"] == "SYMBOL_ERROR"

    def test_symbol_error_suggestions_is_list(self):
        from src import meta as _meta
        err = _meta.make_symbol_error("bad", "t")
        assert isinstance(err["suggestions"], list)

    def test_symbol_error_suggestions_default_not_empty(self):
        from src import meta as _meta
        err = _meta.make_symbol_error("bad", "t")
        assert len(err["suggestions"]) > 0

    def test_symbol_error_accepts_alternative(self):
        from src import meta as _meta
        err = _meta.make_symbol_error("bad", "t", alternative="use_other_tool")
        assert err["alternative"] == "use_other_tool"

    def test_deprecated_error_has_required_keys(self):
        from src import meta as _meta
        err = _meta.make_deprecated_error("old_tool", "removed")
        for key in ("status", "tool", "reason", "suggestions", "alternative"):
            assert key in err, f"make_deprecated_error missing: {key}"

    def test_deprecated_error_status_value(self):
        from src import meta as _meta
        err = _meta.make_deprecated_error("t", "reason")
        assert err["status"] == "TOOL_DEPRECATED"

    def test_deprecated_error_suggestions_is_list(self):
        from src import meta as _meta
        err = _meta.make_deprecated_error("t", "r")
        assert isinstance(err["suggestions"], list)

    def test_time_gated_error_has_required_keys(self):
        from src import meta as _meta
        err = _meta.make_time_gated_error("calculate_rsi")
        for key in ("status", "tool", "reason", "suggestions", "alternative",
                    "available_from", "available_until"):
            assert key in err, f"make_time_gated_error missing: {key}"

    def test_time_gated_error_status_value(self):
        from src import meta as _meta
        err = _meta.make_time_gated_error("t")
        assert err["status"] == "TOOL_TIME_GATED"

    def test_time_gated_error_suggestions_not_empty(self):
        from src import meta as _meta
        err = _meta.make_time_gated_error("t")
        assert isinstance(err["suggestions"], list)
        assert len(err["suggestions"]) > 0

    def test_all_three_errors_share_common_keys(self):
        """All error types must expose the same base key set."""
        from src import meta as _meta
        e1 = _meta.make_symbol_error("", "t")
        e2 = _meta.make_deprecated_error("t", "r")
        e3 = _meta.make_time_gated_error("t")
        common = {"status", "tool", "reason", "suggestions", "alternative"}
        for i, err in enumerate([e1, e2, e3], 1):
            for key in common:
                assert key in err, f"error #{i} missing common key: {key}"

    def test_existing_time_gated_key_set_preserved(self):
        """Sprint 2 contract: TOOL_TIME_GATED response must still have available_from/until."""
        from src import meta as _meta
        err = _meta.make_time_gated_error("calculate_rsi")
        assert "available_from" in err
        assert "available_until" in err


# ---------------------------------------------------------------------------
# D5 — Metadata consistency: all intelligence MCP tools wrapped
# ---------------------------------------------------------------------------

class TestIntelligenceMetaWrap:

    def _vix_data(self):
        return {
            "level": 14.5, "prev_close": 14.0, "change_pct": 3.57,
            "week52_high": 22.0, "week52_low": 10.5, "percentile_52w": 60,
            "interpretation": "Mild uncertainty", "caution_level": "MODERATE",
        }

    def _pulse_data(self):
        return {"overall_sentiment": "RISK_ON", "assets": {}}

    def _events_data(self):
        return {"events": [], "count": 0, "horizon_days": 7}

    def test_get_india_vix_returns_wrapped(self):
        tools = _intel_mcp()
        with patch("src.tools.intelligence._get_india_vix", return_value=self._vix_data()):
            result = tools["get_india_vix"].fn()
        assert "data" in result
        assert "meta" in result

    def test_get_india_vix_data_contains_level(self):
        tools = _intel_mcp()
        with patch("src.tools.intelligence._get_india_vix", return_value=self._vix_data()):
            result = tools["get_india_vix"].fn()
        assert result["data"]["level"] == 14.5

    def test_get_india_vix_meta_has_freshness(self):
        tools = _intel_mcp()
        with patch("src.tools.intelligence._get_india_vix", return_value=self._vix_data()):
            result = tools["get_india_vix"].fn()
        assert "freshness" in result["meta"]

    def test_get_india_vix_error_sets_dq_invalid(self):
        tools = _intel_mcp()
        with patch("src.tools.intelligence._get_india_vix", return_value={"error": "no data"}):
            result = tools["get_india_vix"].fn()
        assert result["meta"]["data_quality"] == "INVALID"

    def test_get_global_pulse_returns_wrapped(self):
        tools = _intel_mcp()
        with patch("src.tools.intelligence._get_global_pulse", return_value=self._pulse_data()):
            result = tools["get_global_pulse"].fn()
        assert "data" in result
        assert "meta" in result

    def test_get_global_pulse_data_has_sentiment(self):
        tools = _intel_mcp()
        with patch("src.tools.intelligence._get_global_pulse", return_value=self._pulse_data()):
            result = tools["get_global_pulse"].fn()
        assert result["data"]["overall_sentiment"] == "RISK_ON"

    def test_get_global_pulse_meta_has_schema_version(self):
        tools = _intel_mcp()
        with patch("src.tools.intelligence._get_global_pulse", return_value=self._pulse_data()):
            result = tools["get_global_pulse"].fn()
        assert result["meta"]["schema_version"] == 5

    def test_get_upcoming_events_returns_wrapped(self):
        tools = _intel_mcp()
        with patch("src.tools.intelligence._get_upcoming_events", return_value=self._events_data()):
            result = tools["get_upcoming_events"].fn(days_ahead=7)
        assert "data" in result
        assert "meta" in result

    def test_get_upcoming_events_data_has_events(self):
        tools = _intel_mcp()
        with patch("src.tools.intelligence._get_upcoming_events", return_value=self._events_data()):
            result = tools["get_upcoming_events"].fn(days_ahead=7)
        assert "events" in result["data"]

    def test_get_upcoming_events_meta_source(self):
        tools = _intel_mcp()
        with patch("src.tools.intelligence._get_upcoming_events", return_value=self._events_data()):
            result = tools["get_upcoming_events"].fn()
        assert "internal" in result["meta"]["source"]

    def test_get_market_risk_score_meta_type_interpretation(self):
        tools = _intel_mcp()
        with patch("src.intelligence.risk.get_market_risk_score", return_value={
            "score": 35, "rating": "MODERATE", "factors": [], "recommendation": "ok", "inputs": {}
        }):
            result = tools["get_market_risk_score"].fn("NIFTY")
        assert result["meta"]["type"] == "INTERPRETATION"


# ---------------------------------------------------------------------------
# D6 — Calendar source_meta transparency
# ---------------------------------------------------------------------------

class TestCalendarSourceTransparency:
    def setup_method(self):
        from src.market import calendar as _cal
        _cal._reset_holiday_cache()

    def teardown_method(self):
        from src.market import calendar as _cal
        _cal._reset_holiday_cache()

    def test_source_meta_holiday_source_not_configured(self):
        """Default stub provider returns None → 'not_configured' in source_meta."""
        from src.market.calendar import get_market_calendar
        with patch("src.market.calendar._live_expiries", return_value={}):
            cal = get_market_calendar()
        assert cal["source_meta"]["holiday_source"] == "not_configured"

    def test_source_meta_holiday_source_provider(self):
        from src.market.calendar import get_market_calendar
        custom = {date(2026, 12, 25): "Test"}
        with patch("src.market.calendar._holiday_provider", return_value=custom):
            with patch("src.market.calendar._live_expiries", return_value={}):
                cal = get_market_calendar()
        assert cal["source_meta"]["holiday_source"] == "provider"

    def test_source_meta_holiday_source_offline(self):
        from src.market.calendar import get_market_calendar
        with patch("src.market.calendar._holiday_provider", side_effect=RuntimeError("net")):
            with patch("src.market.calendar._live_expiries", return_value={}):
                cal = get_market_calendar()
        assert cal["source_meta"]["holiday_source"] == "offline"

    def test_source_meta_expiry_live_when_nse_up(self):
        from src.market.calendar import get_market_calendar
        mock_live = {"nifty": "26-Jun-2025"}
        with patch("src.market.calendar._live_expiries", return_value=mock_live):
            cal = get_market_calendar()
        assert cal["source_meta"]["expiry_source"] == "live"

    def test_source_meta_expiry_algorithmic_when_nse_down(self):
        from src.market.calendar import get_market_calendar
        with patch("src.market.calendar._live_expiries", return_value={}):
            cal = get_market_calendar()
        assert cal["source_meta"]["expiry_source"] == "algorithmic"

    def test_valid_source_values(self):
        """Source values must be from the documented set."""
        valid_holiday_sources = {"provider", "cache", "not_configured", "offline"}
        from src.market.calendar import get_market_calendar
        with patch("src.market.calendar._live_expiries", return_value={}):
            cal = get_market_calendar()
        assert cal["source_meta"]["holiday_source"] in valid_holiday_sources

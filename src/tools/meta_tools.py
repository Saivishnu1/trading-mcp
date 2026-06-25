"""
Phase 23 Sprint 1 — Meta tools.

get_market_calendar  — canonical source for date, session, expiry, and holiday info
get_capabilities     — declare what this MCP instance can and cannot do
get_tool_health      — per-tool health snapshot, callable at session start
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

from mcp.server.fastmcp import FastMCP

import src.meta as _meta
from src.market.calendar import (
    get_market_calendar as _get_market_calendar,
    get_calendar_health as _get_calendar_health,
)

# ---------------------------------------------------------------------------
# Static capability declarations
# ---------------------------------------------------------------------------

_CAPABILITY_FLAGS: dict[str, bool] = {
    "market_calendar": True,
    "option_chain_depth": True,
    "bse_index_options": True,
    "intraday_snapshot": True,
    "intraday_candles": False,
    "fii_dii_flow": False,
    "sector_indices": False,
    "oi_buildup": False,
}

_DATA_LAG: dict[str, str] = {
    "get_quote": "5-15 min",
    "get_ohlc": "5-15 min",
    "get_ltp": "5-15 min",
    "get_intraday_snapshot": "5-15 min",
    "get_nifty_dashboard": "5-15 min",
    "get_banknifty_dashboard": "5-15 min",
    "get_historical_data": "end_of_day",
    "get_india_vix": "15 min",
    "get_nifty_option_chain": "5-15 min",
    "get_banknifty_option_chain": "5-15 min",
    "get_sensex_option_chain": "5-15 min",
    "get_bankex_option_chain": "5-15 min",
    "get_equity_option_chain": "5-15 min",
    "calculate_pcr": "5-15 min",
    "get_oi_analysis": "5-15 min",
    "identify_support_resistance_from_oi": "5-15 min",
    "calculate_max_pain": "5-15 min",
    "calculate_rsi": "end_of_day",
    "calculate_ema": "end_of_day",
    "calculate_macd": "end_of_day",
    "calculate_adx": "end_of_day",
    "calculate_atr": "end_of_day",
    "analyze_technicals": "end_of_day",
    "detect_market_regime": "end_of_day",
    "generate_trade_setup": "end_of_day",
    "get_regime_alignment": "end_of_day",
    "get_symbol_news": "15-60 min",
    "get_news_sentiment": "15-60 min",
    "get_earnings_calendar": "end_of_day",
    "get_event_risk": "15-60 min",
    "get_market_risk_score": "15 min",
    "get_global_pulse": "15 min",
    "get_upcoming_events": "static",
    "get_market_calendar": "real-time",
}

# Deprecated tools: still callable but emit a deprecation notice
_KNOWN_DEPRECATED: list[str] = []

# Broken tools: registered but known non-functional (separate from deprecated)
_KNOWN_BROKEN: list[str] = []

# Tools only available during market hours (time-gated)
_TIME_GATED: list[str] = [
    "calculate_rsi",
    "calculate_ema",
    "calculate_macd",
    "analyze_technicals",
    "get_intraday_snapshot",
]

_MCP_VERSION = "0.1.1"


def _ist_now() -> str:
    IST = timezone(timedelta(hours=5, minutes=30))
    return datetime.now(IST).strftime("%Y-%m-%dT%H:%M:%S+05:30")


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    def get_market_calendar() -> dict:
        """Canonical market calendar — date, trading status, expiries, holidays.

        Returns today's date/session info, nearest option expiry per index,
        days to expiry, upcoming holidays within 30 days, next trading day,
        and a week summary.

        This tool is the authoritative source for expiry and holiday information.
        No authentication required.
        """
        data = _get_market_calendar()
        m = _meta.build_meta(
            type_=_meta.TYPE_FACT,
            validation_status=_meta.VALIDATION_VERIFIED,
            data_quality=_meta.DQ_VALID,
            source="NSE/algorithmic",
            account_type="MARKET_DATA_ONLY",
            stale_threshold_seconds=86400,
        )
        return _meta.wrap(data, m)

    @mcp.tool()
    def get_capabilities() -> dict:
        """Declare what this MCP instance can and cannot do.

        Includes capability flags, per-tool data lag, known broken tools,
        time-gated tools, and version metadata.

        No authentication required.
        """
        try:
            all_tools = [t.name for t in mcp._tool_manager.list_tools()]
        except Exception:
            all_tools = []

        data = {
            "capabilities": _CAPABILITY_FLAGS,
            "data_lag": {
                tool: lag
                for tool, lag in _DATA_LAG.items()
                if tool in all_tools or tool == "get_market_calendar"
            },
            "known_broken": _KNOWN_BROKEN,
            "deprecated": _KNOWN_DEPRECATED,
            "time_gated": _TIME_GATED,
            "meta": {
                "as_of": _ist_now(),
                "mcp_version": _MCP_VERSION,
                "total_tools": len(all_tools),
            },
        }
        m = _meta.build_meta(
            type_=_meta.TYPE_FACT,
            validation_status=_meta.VALIDATION_VERIFIED,
            data_quality=_meta.DQ_VALID,
            source="internal",
            account_type="MARKET_DATA_ONLY",
            stale_threshold_seconds=3600,
        )
        return _meta.wrap(data, m)

    @mcp.tool()
    def get_tool_health() -> dict:
        """Per-tool health snapshot. Call at session start to understand server state.

        Counts healthy / degraded / deprecated / time_gated / total tools.
        All counts are derived dynamically from the live tool registry.

        No authentication required.
        """
        try:
            all_tools = [t.name for t in mcp._tool_manager.list_tools()]
        except Exception:
            all_tools = []

        deprecated_set = set(_KNOWN_DEPRECATED)
        time_gated_set = set(_TIME_GATED)

        tools_detail: dict[str, dict] = {}
        healthy = degraded = deprecated = time_gated = 0

        for name in all_tools:
            if name in deprecated_set:
                status = "deprecated"
                reason = "Tool has been deprecated; see alternative."
                severity = "WARNING"
                recommended_action = "Check 'alternative' field in error response."
                deprecated += 1
            elif name in time_gated_set:
                status = "time_gated"
                reason = "Available only during NSE session 09:15–15:30 IST."
                severity = "INFO"
                recommended_action = "Use get_historical_data for offline analysis."
                time_gated += 1
            else:
                status = "healthy"
                reason = None
                severity = "INFO"
                recommended_action = None
                healthy += 1
            entry: dict = {
                "status": status,
                "data_lag": _DATA_LAG.get(name, "unknown"),
                "severity": severity,
            }
            if reason:
                entry["reason"] = reason
            if recommended_action:
                entry["recommended_action"] = recommended_action
            tools_detail[name] = entry

        # Enrich get_market_calendar entry with calendar health detail
        if "get_market_calendar" in tools_detail:
            try:
                cal_health = _get_calendar_health()
                cal_status = cal_health["status"]
                tools_detail["get_market_calendar"]["holiday_source"] = cal_health["holiday_source"]
                tools_detail["get_market_calendar"]["expiry_source"] = cal_health["expiry_source"]
                tools_detail["get_market_calendar"]["calendar_status"] = cal_status
                if cal_health.get("severity"):
                    tools_detail["get_market_calendar"]["severity"] = cal_health["severity"]
                if cal_health.get("reason"):
                    tools_detail["get_market_calendar"]["reason"] = cal_health["reason"]
                if cal_health.get("recommended_action"):
                    tools_detail["get_market_calendar"]["recommended_action"] = cal_health["recommended_action"]
                # HEALTHY and CACHED are normal operation — not degraded
                # EMERGENCY and FAILED degrade the tool health count
                if cal_status in ("EMERGENCY", "FAILED"):
                    if tools_detail["get_market_calendar"]["status"] == "healthy":
                        healthy -= 1
                        degraded += 1
                    tools_detail["get_market_calendar"]["status"] = "degraded"
            except Exception:
                pass

        data = {
            "summary": {
                "healthy": healthy,
                "degraded": degraded,
                "deprecated": deprecated,
                "time_gated": time_gated,
                "total": len(all_tools),
            },
            "tools": tools_detail,
            "meta": {
                "checked_at": _ist_now(),
                "market_open": _meta.is_market_hours(),
            },
        }
        m = _meta.build_meta(
            type_=_meta.TYPE_FACT,
            validation_status=_meta.VALIDATION_VERIFIED,
            data_quality=_meta.DQ_VALID,
            source="internal",
            account_type="MARKET_DATA_ONLY",
            stale_threshold_seconds=300,
        )
        return _meta.wrap(data, m)

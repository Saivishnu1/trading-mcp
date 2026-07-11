from __future__ import annotations

import time
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))

MCP_MANIFEST: dict = {
    "name": "zerodha-trading-intelligence",
    "version": "1.0",
    "description": (
        "Personal trading intelligence platform for Indian markets. "
        "Provides market analysis, pattern detection, option structure, "
        "position monitoring with Telegram alerts, trade journal, "
        "and trade planning. "
        "NOT a data provider — use companion MCPs for raw stock prices, "
        "mutual funds, US stocks, networth, and order placement."
    ),

    "tool_capabilities": {
        "market_intelligence": [
            "analyze_chart",
            "detect_candlestick_patterns",
            "detect_chart_patterns",
            "analyze_option_structure",
            "get_market_awareness",
        ],
        "option_chains": [
            "get_nifty_option_chain",
            "get_banknifty_option_chain",
            "get_sensex_option_chain",
            "get_bankex_option_chain",
            "get_equity_option_chain",
            "get_option_chain_depth",
            "calculate_pcr",
            "calculate_max_pain",
            "get_expiries",
        ],
        "broker_data": [
            "get_unified_holdings",
            "get_unified_positions",
            "get_unified_orders",
            "get_unified_funds",
            "get_broker_status",
            "get_all_open_positions",
        ],
        "monitor": [
            "get_monitor_status",
            "get_recent_alerts",
            "update_monitor_settings",
            "test_whatsapp_alert",
            "sync_positions",
        ],
        "journal": [
            "log_trade",
            "close_trade",
            "get_open_trades",
            "get_trade_history",
            "get_performance_analytics",
            "review_trade",
            "review_open_trades",
            "sync_trades_from_zerodha",
            "get_trade_cost_estimate",
            "get_net_pnl_today",
            "get_strike_attempts",
        ],
        "trade_planning": [
            "create_trade_plan",
            "build_option_strategy",
            "calculate_risk_reward",
            "calculate_position_size",
            "calculate_atr",
            "size_options_trade",
            "project_carry_cost",
        ],
        "commodities": [
            "check_benchmark_divergence",
        ],
        "catalyst": [
            "get_earnings_calendar",
            "check_move_news_correlation",
        ],
        "market_data": [
            "get_market_calendar",
            "get_india_vix",
            "get_global_pulse",
            "get_upcoming_events",
            "get_nifty_dashboard",
            "get_banknifty_dashboard",
            "get_sensex_dashboard",
        ],
        "charts": [
            "get_price_chart",
            "get_indicator_chart",
            "get_option_chart",
        ],
        "auth": [
            "zerodha_login",
            "zerodha_logout",
            "check_auth_status",
            "get_profile",
            "get_broker_status",
        ],
        "meta": [
            "get_capabilities",
            "get_tool_health",
        ],
    },

    "data_boundaries": {
        "handles": [
            "NSE/BSE option chain analysis — PCR, max pain, OI walls, IV",
            "Technical chart analysis — trend, structure, S/R, indicators",
            "Candlestick pattern detection — 22 patterns with volume context",
            "Chart pattern detection — double top/bottom, H&S, triangles, flags",
            "Composite market awareness — all of the above in one call",
            "Position monitoring with Telegram alerts and trailing SL",
            "Trade journal and performance analytics",
            "Trade planning, sizing, and strategy building",
            "Market calendar — live expiry dates, NSE/BSE holidays",
            "Cross-broker unified portfolio — Zerodha + INDmoney combined",
            "Global market pulse — crude, gold, DXY, S&P500",
            "Visual charts — candlestick PNG with overlays",
            "Cross-broker unified open positions across all segments including MCX passthrough",
            "MCX commodity benchmark divergence (crude/nat-gas only, vs WTI/Henry Hub) — benchmark side only, MCX price is caller-supplied",
            "Cost-adjusted net P&L and directional brokerage/STT cost estimates",
            "Re-entry pattern detection and strike-level attempt tally (observational only)",
            "Move-news correlation for large intraday moves",
            "Multi-day carry-cost (time-decay) projection",
        ],
        "does_not_handle": [
            "Raw stock price lookup → use Indmoney MCP:get_indian_stocks_details",
            "Mutual fund data → use Indmoney MCP:get_mf_funds_details",
            "US stock data → use Indmoney MCP:get_us_stocks_details",
            "Networth and liabilities → use Indmoney MCP:networth_snapshot",
            "SIP tracking → use Indmoney MCP:mf_sips or indian_stocks_sips",
            "Top gainers/losers → use Indmoney MCP:get_indian_stocks_movers",
            "Watchlist → use Indmoney MCP:user_watchlist",
            "Symbol lookup → use Indmoney MCP:lookup_ind_keys",
            "Greeks history → use Indmoney MCP:get_indian_stocks_greeks_history",
            "Order placement → use Kite MCP:place_order when available",
            "GTT orders → use Kite MCP:place_gtt_order when available",
            "MCX symbol resolution, option chains, dashboards, quotes → NOT AVAILABLE from any source (no Kite Connect subscription, INDstocks has no MCX/commodity coverage — see docs/research/mcx_scope_20260711.md). Only check_benchmark_divergence's international-benchmark half works today.",
        ],
    },

    "companion_mcps": {
        "indmoney_mcp": {
            "name": "Indmoney MCP",
            "url": "https://mcp.indmoney.com/mcp",
            "status": "available",
            "handles": [
                "stock details and live prices",
                "networth and liabilities",
                "mutual funds and SIPs",
                "US stocks",
                "top gainers/losers/movers",
                "option chain and Greeks history",
                "symbol/scrip code lookup",
                "watchlist",
            ],
        },
        "kite_mcp": {
            "name": "Zerodha Kite MCP",
            "url": "https://mcp.kite.trade/mcp",
            "status": "unavailable",
            "note": (
                "Authentication broken on Claude.ai as of July 2026. "
                "Zerodha acknowledged issue. "
                "JugaadClient used as fallback for Zerodha data. "
                "When fixed: use for order placement, GTT, holdings, quotes."
            ),
            "handles_when_available": [
                "order placement",
                "GTT orders",
                "holdings",
                "positions",
                "historical data",
                "live quotes",
                "instrument search",
            ],
        },
    },

    "routing_rules": {
        "live_quotes": {
            "kite_mcp_available": "Zerodha_kite_mcp:get_ltp",
            "kite_mcp_unavailable": "our get_ltp via JugaadClient",
        },
        "holdings": {
            "kite_mcp_available": "Zerodha_kite_mcp:get_holdings",
            "kite_mcp_unavailable": "our get_holdings via JugaadClient",
        },
        "historical_data": {
            "kite_mcp_available": "Zerodha_kite_mcp:get_historical_data",
            "kite_mcp_unavailable": "our get_historical_data via JugaadClient",
        },
        "order_placement": {
            "kite_mcp_available": "Zerodha_kite_mcp:place_order",
            "kite_mcp_unavailable": "NOT AVAILABLE — inform user to place manually",
        },
        "gtt_orders": {
            "kite_mcp_available": "Zerodha_kite_mcp:place_gtt_order",
            "kite_mcp_unavailable": "NOT AVAILABLE — inform user to set GTT manually in app",
        },
        "stock_details": {
            "always": "Indmoney MCP:get_indian_stocks_details",
        },
        "networth": {
            "always": "Indmoney MCP:networth_snapshot",
        },
        "mutual_funds": {
            "always": "Indmoney MCP:get_mf_funds_details",
        },
        "symbol_lookup": {
            "always": "Indmoney MCP:lookup_ind_keys",
        },
        "option_analysis": {
            "always": "our analyze_option_structure",
            "note": "Superior to INDmoney option chain — includes PCR, max pain, OI walls, IV skew",
        },
        "chart_analysis": {
            "always": "our analyze_chart",
            "note": "Not available in any other MCP",
        },
        "pattern_detection": {
            "always": "our detect_candlestick_patterns + detect_chart_patterns",
            "note": "Not available in any other MCP",
        },
        "market_awareness": {
            "always": "our get_market_awareness",
            "note": "Composite tool — combines chart, patterns, OI, global in one call",
        },
        "position_monitoring": {
            "always": "our monitor system",
            "note": "Unique capability — trailing SL, Telegram alerts, auto-sync",
        },
        "trade_journal": {
            "always": "our journal tools",
            "note": "Unique capability — not available in any other MCP",
        },
    },

    "recommended_workflows": {
        "morning_session": [
            "1. get_market_calendar() — expiry dates, holidays",
            "2. get_market_awareness(symbol) — full intelligence",
            "3. analyze_option_structure(symbol) — OI and IV",
            "4. get_monitor_status() — open positions and trailing SL",
            "5. Indmoney MCP:get_indian_stocks_movers — top gainers/losers",
        ],
        "trade_entry": [
            "1. get_market_awareness(symbol) — confirm structure",
            "2. analyze_option_structure(symbol) — confirm OI setup",
            "3. create_trade_plan(symbol) — entry/SL/target",
            "4. size_options_trade() — position sizing",
            "5. log_trade() — record in journal after entry",
        ],
        "trade_monitoring": [
            "1. get_monitor_status() — trailing SL levels",
            "2. get_recent_alerts() — alerts fired",
            "3. analyze_option_structure(symbol) — OI shifts",
            "4. review_open_trades() — full position review",
        ],
        "post_trade": [
            "1. close_trade() — update journal",
            "2. review_trade() — what worked, what didn't",
            "3. get_performance_analytics() — track edge over time",
        ],
        "portfolio_review": [
            "1. Indmoney MCP:networth_snapshot — full wealth picture",
            "2. get_unified_holdings() — cross-broker holdings",
            "3. get_unified_positions() — open F&O positions",
            "4. analyze_portfolio() — sector, concentration, P&L",
        ],
    },
}

_KITE_STATUS_CACHE: dict = {"status": None, "checked_at": 0.0}
_KITE_STATUS_TTL_SECONDS = 300


def get_kite_mcp_status() -> str:
    """Returns "available" | "unavailable" for the companion Kite MCP, cached for 5 minutes.

    There is no live Kite MCP endpoint reachable from this server to probe, so this
    reflects the last known status recorded in MCP_MANIFEST — unavailable due to a
    broken Claude.ai auth flow (see companion_mcps.kite_mcp.note).
    """
    now = time.monotonic()
    if _KITE_STATUS_CACHE["status"] is not None and (now - _KITE_STATUS_CACHE["checked_at"]) < _KITE_STATUS_TTL_SECONDS:
        return _KITE_STATUS_CACHE["status"]

    status = MCP_MANIFEST["companion_mcps"]["kite_mcp"]["status"]
    _KITE_STATUS_CACHE["status"] = status
    _KITE_STATUS_CACHE["checked_at"] = now
    return status

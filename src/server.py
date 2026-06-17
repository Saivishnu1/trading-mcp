import os
import logging
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from src.broker import get_broker
from src.tools import auth, portfolio, market, instruments, options, technicals, analysis, dashboard, trade_planner, strategy_builder, trade_review, intelligence

load_dotenv()
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))

# Restore persisted session so users survive server restarts without re-login
_session_file = os.environ.get("SESSION_FILE", ".session.json")
get_broker().load_session(_session_file)

_allowed_host = os.environ.get("PUBLIC_HOST", "zerodha-mcp-production.up.railway.app")

mcp = FastMCP(
    name="Zerodha Personal MCP",
    transport_security=TransportSecuritySettings(
        allowed_hosts=[_allowed_host, f"{_allowed_host}:443", "localhost", "localhost:8000"],
    ),
    instructions=(
        "Zerodha personal-account MCP server — no paid Kite Connect subscription needed.\n\n"
        "AUTHENTICATION (required for portfolio tools):\n"
        "  Call zerodha_login(user_id, password, totp_code='123456') once.\n"
        "  The session is saved to disk and reloaded on restart (~24 h lifetime).\n"
        "  Alternatively, pass totp_secret instead of totp_code for auto-generation.\n\n"
        "PORTFOLIO tools (require active session):\n"
        "  get_holdings()          — demat holdings\n"
        "  get_positions()         — intraday/net positions\n"
        "  get_margins([segment])  — available funds\n\n"
        "MARKET DATA tools (no auth needed, free sources):\n"
        "  get_quote(['NSE:INFY'])                    — full quote\n"
        "  get_ohlc(['NSE:TCS'])                      — OHLC snapshot\n"
        "  get_ltp(['NSE:INFY','BSE:RELIANCE'])       — last price only\n"
        "  get_historical_data('NSE:INFY','2024-01-01','2024-12-31','1d')\n\n"
        "INSTRUMENTS tools (no auth needed):\n"
        "  search_instruments('Infosys')              — symbol/name search\n"
        "  get_instruments('NSE')                     — full NSE equity list\n"
        "  invalidate_instruments_cache()             — refresh the local list\n\n"
        "OPTIONS tools (NSE index + equity options, no auth needed):\n"
        "  get_expiries('NIFTY')                      — available expiry dates\n"
        "  get_nifty_option_chain([expiry])           — NIFTY chain (CE/PE OI, IV, LTP)\n"
        "  get_banknifty_option_chain([expiry])       — BANKNIFTY chain\n"
        "  get_equity_option_chain('RELIANCE')        — any NSE F&O equity chain\n"
        "  calculate_pcr('NIFTY')                     — put-call ratio + sentiment\n"
        "  get_oi_analysis('NIFTY')                   — top OI strikes\n"
        "  identify_support_resistance_from_oi('NIFTY') — S/R from OI\n"
        "  calculate_max_pain('NIFTY')                — max pain strike\n\n"
        "TECHNICALS tools (daily candles via Yahoo Finance, no auth needed):\n"
        "  calculate_rsi('NIFTY', period=14)          — Relative Strength Index\n"
        "  calculate_ema('NIFTY', period=20)          — Exponential Moving Average\n"
        "  calculate_macd('NIFTY')                    — MACD 12/26/9\n"
        "  calculate_adx('NIFTY')                     — ADX + DI (trend strength)\n"
        "  calculate_atr('NIFTY')                     — Average True Range (volatility)\n"
        "  analyze_technicals('NIFTY')                — all indicators in one call\n"
        "  Symbols: 'NIFTY','BANKNIFTY','NSE:INFY', or raw yfinance tickers.\n\n"
        "ANALYSIS tools (deterministic trade analysis, no auth needed):\n"
        "  detect_market_regime('NIFTY')             — bull/bear/range/breakout regime\n"
        "  generate_trade_setup('NIFTY')             — BUY/SELL/NEUTRAL setup\n"
        "  recommend_strategy('NIFTY')               — options strategy suggestion\n"
        "  calculate_risk_reward(100, 95, 110)       — risk/reward ratio\n"
        "  calculate_position_size(100000, 1, 100, 95) — sizing by capital risk\n\n"
        "DASHBOARD tools (single-call daily briefing, no auth needed):\n"
        "  get_nifty_dashboard()      — full NIFTY snapshot: options + technicals + regime + setup\n"
        "  get_banknifty_dashboard()  — full BANKNIFTY snapshot\n\n"
        "TRADE PLANNER tools (read-only execution planning, no auth needed):\n"
        "  create_trade_plan('NIFTY', capital=100000, risk_percent=1)\n"
        "    — entry/stoploss/target + position size + trade quality + strategy\n\n"
        "OPTION STRATEGY BUILDER tools (concrete strikes + payoffs, no auth needed):\n"
        "  build_option_strategy('NIFTY', expiry='23-Jun-2026')\n"
        "    — legs, premiums, max loss, max profit, breakeven from live chain\n\n"
        "TRADE REVIEW tools (thesis evaluation, no auth needed):\n"
        "  review_trade('NSE:INFY', direction='LONG', entry_price=1400, holding_days=3)\n"
        "    — HOLD / REDUCE / EXIT + thesis status + invalidation conditions\n\n"
        "MARKET INTELLIGENCE tools (macro context, no auth needed):\n"
        "  get_india_vix()                          — VIX level, 52w percentile, caution level\n"
        "  get_global_pulse()                       — crude, gold, DXY, S&P500, US10Y + sentiment\n"
        "  get_upcoming_events(days_ahead=7)        — RBI MPC, FOMC, CPI, GDP, NFP schedule\n"
        "  get_market_risk_score(symbol='NIFTY')    — composite 0-100 risk score\n\n"
        "Symbol format: 'EXCHANGE:SYMBOL' e.g. 'NSE:INFY', 'BSE:RELIANCE'.\n"
        "Indices: 'NSE:NIFTY 50', 'NSE:SENSEX', or yfinance tickers like '^NSEI'.\n\n"
        "BROKER BACKEND (set BROKER_BACKEND env var):\n"
        "  zerodha_web (default) — direct httpx calls to kite.zerodha.com\n"
        "  jugaad               — jugaad-trader fallback\n"
    ),
)

auth.register(mcp)
portfolio.register(mcp)
market.register(mcp)
instruments.register(mcp)
options.register(mcp)
technicals.register(mcp)
analysis.register(mcp)
dashboard.register(mcp)
trade_planner.register(mcp)
strategy_builder.register(mcp)
trade_review.register(mcp)
intelligence.register(mcp)

_sse_app = mcp.sse_app()
_http_app = mcp.streamable_http_app()


async def app(scope, receive, send):
    if scope["type"] == "http":
        path = scope.get("path", "")
        if path == "/health":
            body = b'{"status":"ok"}'
            await send({"type": "http.response.start", "status": 200,
                        "headers": [[b"content-type", b"application/json"],
                                    [b"content-length", str(len(body)).encode()]]})
            await send({"type": "http.response.body", "body": body})
            return
        if path == "/sse" or path.startswith("/messages"):
            await _sse_app(scope, receive, send)
            return
    # /mcp requests AND lifespan events go to http_app so it can
    # initialize its session manager task group during startup.
    await _http_app(scope, receive, send)


def main() -> None:
    import uvicorn
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host=host, port=port)


def main_stdio() -> None:
    mcp.run("stdio")


if __name__ == "__main__":
    main()

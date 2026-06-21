import json
import os
import logging
import urllib.parse
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from src.broker import get_broker
from src.tools import auth, portfolio, market, instruments, options, technicals, analysis, dashboard, trade_planner, strategy_builder, trade_review, intelligence, portfolio_intelligence, catalyst, journal, recommendations, sizer, calibration, recommendation_log
import src.session_store as session_store

load_dotenv()
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))

logger = logging.getLogger(__name__)

# Restore persisted session from DB so users survive server restarts without re-login
def _restore_session() -> None:
    enctoken = session_store.load()
    if enctoken:
        get_broker().set_enctoken(enctoken)
        logger.info("Session restored from DB")

try:
    _restore_session()
except Exception as exc:
    logger.warning("Could not restore session from DB: %s", exc)



_allowed_host = os.environ.get("PUBLIC_HOST", "zerodha-mcp-production.up.railway.app")

mcp = FastMCP(
    name="Zerodha Personal MCP",
    transport_security=TransportSecuritySettings(
        allowed_hosts=[_allowed_host, f"{_allowed_host}:443", "localhost", "localhost:8000"],
    ),
    instructions=(
        "Zerodha personal-account MCP server — no paid Kite Connect subscription needed.\n\n"
        "AUTHENTICATION (required for portfolio tools):\n"
        "  Call zerodha_login() — it returns a login_url if not authenticated.\n"
        "  Tell the user to open that URL in their browser and enter credentials directly.\n"
        "  NEVER ask for or accept passwords or TOTP codes — credentials must not pass through the agent.\n"
        "  The session is saved to disk and reloaded on restart (~24 h lifetime).\n\n"
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
        "PORTFOLIO INTELLIGENCE tools (require active session):\n"
        "  get_portfolio_risk_report()       — per-position risk scores + portfolio risk + recommendations\n"
        "  get_portfolio_regime_analysis()   — regime distribution + directional bias across holdings\n"
        "  get_portfolio_exposure_breakdown() — long/short exposure, concentration, diversification\n\n"
        "CATALYST INTELLIGENCE tools (news, earnings, event risk, no auth needed):\n"
        "  get_symbol_news('INFY', count=10) — recent headlines + per-article sentiment\n"
        "  get_news_sentiment('INFY')        — aggregate sentiment score and counts\n"
        "  get_earnings_calendar('INFY')     — next earnings date, EPS estimate, dividends, splits\n"
        "  get_event_risk('INFY')            — composite 0-100 event risk: earnings + news + market\n\n"
        "POSITION SIZING tools (portfolio-aware, no auth needed):\n"
        "  size_equity_trade('INFY', 'LONG', entry=1540, stoploss=1490, capital=100000)\n"
        "    — quantity, capital_required, max_loss; adjusts for portfolio heat\n"
        "    — returns log_trade_params with risk_amount, capital_at_risk, portfolio_heat_at_entry\n"
        "  size_options_trade('NIFTY', 'LONG', premium=120, stoploss_premium=60, lot_size=50)\n"
        "    — lots, quantity, capital_required; warns when single-position risk > 5%\n"
        "  size_from_recommendation('INFY', capital=100000, risk_percent=1)\n"
        "    — calls recommend_trade() then adds full absolute sizing + log_trade_params\n"
        "    — returns null sizing fields when recommendation is AVOID\n\n"
        "TRADE RECOMMENDATIONS tools (portfolio-aware, no auth needed):\n"
        "  recommend_trade('INFY', capital=100000, risk_percent=1)\n"
        "    — ENTER / WAIT / AVOID with direction, sizing, event risk, VIX context\n"
        "    — warns on duplicate journal exposure; blocks on extreme event risk or VIX\n"
        "    — position_size adjusted for HIGH event risk (−30%) and duplicate exposure (−50%)\n"
        "  review_open_trades()\n"
        "    — live review of all open journal positions: HOLD / REDUCE / EXIT\n"
        "    — current_price, current_pnl, stoploss_breached, target_reached per position\n"
        "  get_daily_brief()\n"
        "    — morning briefing: VIX + global sentiment + risk score + position review + alerts\n\n"
        "TRADE JOURNAL tools (persistent SQLite journal, no auth needed):\n"
        "  log_trade('INFY', 'LONG', 1540.0, stoploss=1490, target=1640)\n"
        "    — record a new trade; returns trade_id (format TRD-xxxxxxxx)\n"
        "    — pass regime/signal/risk_score from prior analysis calls in the session\n"
        "    — analysis_snapshot: dict of any extra context to preserve at entry\n"
        "    — trade_type: 'EQUITY' (default) | 'OPTIONS' | 'FUTURES' | 'INDEX'\n"
        "    — created_by: 'MANUAL' (default) | 'CLAUDE' | 'AUTOMATED'\n"
        "  close_trade('TRD-xxxxxxxx', 1635.0, exit_reason='TARGET_HIT')\n"
        "    — finalise position; calculates pnl, pnl_percent, holding_days\n"
        "    — exit_reason: TARGET_HIT | STOPLOSS_HIT | MANUAL | THESIS_INVALIDATED | EXPIRED | CANCELLED\n"
        "  get_open_trades([symbol])         — list open positions (filter by symbol optional)\n"
        "  get_trade_history([symbol, days, status, limit])\n"
        "    — query history + summary: win_rate, total_pnl, avg_holding_days, best/worst trade\n\n"
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
portfolio_intelligence.register(mcp)
catalyst.register(mcp)
journal.register(mcp)
recommendations.register(mcp)
sizer.register(mcp)
calibration.register(mcp)
recommendation_log.register(mcp)

_sse_app = mcp.sse_app()
_http_app = mcp.streamable_http_app()


_UI_DIR = os.path.join(os.path.dirname(__file__), "ui")
_LOGIN_TEMPLATE = open(os.path.join(_UI_DIR, "login.html"), encoding="utf-8").read()


async def _read_body(receive) -> bytes:
    body = b""
    more = True
    while more:
        msg = await receive()
        body += msg.get("body", b"")
        more = msg.get("more_body", False)
    return body


async def _send_html(send, status: int, html: str) -> None:
    body = html.encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [[b"content-type", b"text/html; charset=utf-8"],
                             [b"content-length", str(len(body)).encode()]]})
    await send({"type": "http.response.body", "body": body})


async def _send_json(send, status: int, data: dict) -> None:
    body = json.dumps(data).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [[b"content-type", b"application/json"],
                             [b"content-length", str(len(body)).encode()]]})
    await send({"type": "http.response.body", "body": body})


def _render_login(prefill_user_id: str, message: str) -> str:
    return (
        _LOGIN_TEMPLATE
        .replace("{prefill_user_id}", prefill_user_id)
        .replace("{message}", message)
    )


async def _handle_login_get(send) -> None:
    prefill = os.environ.get("ZERODHA_USER_ID", "")
    await _send_html(send, 200, _render_login(prefill, ""))


async def _handle_login_post(receive, send) -> None:
    raw = await _read_body(receive)
    params = urllib.parse.parse_qs(raw.decode(), keep_blank_values=False)
    user_id   = (params.get("user_id",   [""])[0]).strip()
    password  = (params.get("password",  [""])[0]).strip()
    totp_code = (params.get("totp_code", [""])[0]).strip()

    if not (user_id and password and totp_code):
        prefill = os.environ.get("ZERODHA_USER_ID", "")
        msg = '<p class="msg err">All fields are required.</p>'
        await _send_html(send, 400, _render_login(prefill, msg))
        return

    try:
        broker = get_broker()
        broker.login(user_id=user_id, password=password, totp=totp_code)
    except Exception as exc:
        logger.warning("Browser login failed: %s", exc)
        prefill = os.environ.get("ZERODHA_USER_ID", "")
        msg = f'<p class="msg err">Login failed: {exc}</p>'
        await _send_html(send, 401, _render_login(prefill, msg))
        return

    # Persist session to DB — non-fatal if DB save fails
    enctoken = broker.get_enctoken()
    if enctoken:
        try:
            session_store.save(user_id, enctoken)
        except Exception as exc:
            logger.warning("Could not persist session to DB for %s: %s", user_id, exc)
    else:
        logger.warning("Login succeeded for %s but broker returned no enctoken — session not persisted", user_id)

    logger.info("Browser login successful for %s", user_id)
    msg = '<p class="msg ok">Logged in successfully. You can close this tab.</p>'
    await _send_html(send, 200, _render_login("", msg))


async def app(scope, receive, send):
    if scope["type"] == "http":
        path = scope.get("path", "")
        method = scope.get("method", "GET")

        if path == "/health":
            await _send_json(send, 200, {"status": "ok"})
            return

        if path == "/login" and method == "GET":
            await _handle_login_get(send)
            return

        if path == "/login" and method == "POST":
            await _handle_login_post(receive, send)
            return

        if path == "/auth/status":
            broker = get_broker()
            await _send_json(send, 200, {
                "authenticated": broker.is_authenticated(),
                "backend": type(broker).__name__,
            })
            return

        if path == "/logout" and method == "GET":
            qs = urllib.parse.parse_qs(scope.get("query_string", b"").decode())
            uid = (qs.get("user_id", [""])[0]).strip()
            if uid:
                session_store.delete(uid)
            broker = get_broker()
            broker.clear_enctoken()
            logger.info("Logout: %s", uid or "unknown")
            await _send_json(send, 200, {"logged_out": True, "user_id": uid or None})
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

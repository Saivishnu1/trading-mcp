import json
import os
import logging
import urllib.parse
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from src.broker import get_broker, current_user
from src.tools import auth, portfolio, market, instruments, options, technicals, analysis, dashboard, trade_planner, strategy_builder, trade_review, intelligence, portfolio_intelligence, catalyst, journal, recommendations, sizer, meta_tools, brokers, chart, candles, chart_patterns, options_awareness, market_awareness, charts, monitor, costs, mcx
import src.session_store as session_store
import src.api_key_store as api_key_store

load_dotenv()
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))

logger = logging.getLogger(__name__)

# Restore persisted session from DB so users survive server restarts without re-login
def _restore_session() -> None:
    uid = session_store.get_active_user_id()
    enctoken = session_store.load(uid) if uid else None
    if enctoken and uid:
        get_broker().set_enctoken(enctoken)
        logger.info("Session restored from DB: user_id=%s", uid)

try:
    _restore_session()
except Exception as exc:
    logger.warning("Could not restore session from DB: %s", exc)


def _auto_login_from_env() -> None:
    """Auto-login using env credentials when JUGAAD_USE_ENV_CREDENTIALS=true."""
    if os.environ.get("JUGAAD_USE_ENV_CREDENTIALS", "").lower() != "true":
        return
    user_id     = os.environ.get("ZERODHA_USER_ID", "").strip()
    password    = os.environ.get("ZERODHA_PASSWORD", "").strip()
    totp_secret = os.environ.get("ZERODHA_TOTP_SECRET", "").strip()
    if not (user_id and password and totp_secret):
        logger.warning(
            "JUGAAD_USE_ENV_CREDENTIALS=true but ZERODHA_USER_ID / "
            "ZERODHA_PASSWORD / ZERODHA_TOTP_SECRET are not all set"
        )
        return
    if get_broker().is_authenticated():
        logger.info("Auto-login skipped: session already active")
        return
    try:
        import pyotp
        totp = pyotp.TOTP(totp_secret).now()
    except ImportError:
        logger.error(
            "JUGAAD_USE_ENV_CREDENTIALS=true but pyotp is not installed; "
            "run: uv add pyotp"
        )
        return
    try:
        broker = get_broker()
        broker.login(user_id=user_id, password=password, totp=totp)
        enctoken = broker.get_enctoken()
        if enctoken:
            session_store.save(user_id, enctoken)
            api_key_store.get_or_create(user_id)
            get_broker(user_id).set_enctoken(enctoken)
        logger.info("Auto-login from env successful: %s", user_id)
    except Exception as exc:
        logger.error("Auto-login from env failed: %s", exc)


try:
    _auto_login_from_env()
except Exception as exc:
    logger.warning("Auto-login from env error: %s", exc)


def _refresh_calendar_background() -> None:
    """Refresh NSE holiday calendar from live API in a background thread on startup."""
    import threading

    def _run() -> None:
        try:
            from src.providers.calendar.refresh import refresh_calendar
            result = refresh_calendar()
            if result.get("updated"):
                logger.info(
                    "Calendar auto-refreshed: %d change(s) — %s",
                    len(result.get("changes", [])),
                    result.get("message", ""),
                )
            else:
                logger.debug("Calendar auto-refresh: %s", result.get("message", "no changes"))
        except Exception as exc:
            logger.warning("Calendar auto-refresh failed (static JSON in use): %s", exc)

    threading.Thread(target=_run, daemon=True, name="calendar-refresh").start()


try:
    _refresh_calendar_background()
except Exception as exc:
    logger.warning("Calendar background refresh error: %s", exc)


def _warm_instrument_cache_background() -> None:
    """Pre-fetch the INDstocks equity + fno instrument masters on startup so
    the FIRST /trade search of the day doesn't pay the full CSV download —
    previously the dominant cost behind a "slow" first search (see the
    process-wide TTL cache in src/brokers/indmoney.py). Own thread + own
    event loop (asyncio.run) since this runs before the main app's event
    loop exists, mirroring _refresh_calendar_background()'s pattern.
    """
    import threading

    def _run() -> None:
        try:
            import asyncio
            from src.brokers.factory import get_broker_adapter
            asyncio.run(get_broker_adapter("indmoney").warm_instrument_cache())
            logger.info("Instrument cache pre-warmed (equity + fno).")
        except Exception as exc:
            logger.warning("Instrument cache warm-up failed (will lazy-load on first search): %s", exc)

    threading.Thread(target=_run, daemon=True, name="instrument-cache-warmup").start()


try:
    _warm_instrument_cache_background()
except Exception as exc:
    logger.warning("Instrument cache warm-up error: %s", exc)


_public_host = os.environ.get("PUBLIC_HOST", "")
_allowed_hosts = ["localhost", "localhost:8000", "127.0.0.1", "127.0.0.1:8000"]
if _public_host:
    _allowed_hosts += [_public_host, f"{_public_host}:443"]
# Also accept host derived from PUBLIC_URL if set
_public_url = os.environ.get("PUBLIC_URL", "")
if _public_url:
    from urllib.parse import urlparse as _urlparse
    _pu = _urlparse(_public_url)
    if _pu.hostname and _pu.hostname not in _allowed_hosts:
        _allowed_hosts.append(_pu.hostname)
        _allowed_hosts.append(f"{_pu.hostname}:443")

mcp = FastMCP(
    name="Zerodha Personal MCP",
    transport_security=TransportSecuritySettings(
        allowed_hosts=_allowed_hosts,
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
        "  get_sensex_option_chain([expiry])          — SENSEX chain\n"
        "  get_bankex_option_chain([expiry])          — BANKEX chain\n"
        "  get_equity_option_chain('RELIANCE')        — any NSE F&O equity chain\n"
        "  calculate_pcr('NIFTY')                     — put-call ratio + sentiment\n"
        "  calculate_max_pain('NIFTY')                — max pain strike\n"
        "  analyze_option_structure('NIFTY')          — unified OI walls, PCR, IV skew, max pain\n\n"
        "TECHNICALS tools (daily candles via Yahoo Finance, no auth needed):\n"
        "  calculate_rsi('NIFTY', period=14)          — Relative Strength Index\n"
        "  calculate_ema('NIFTY', period=20)          — Exponential Moving Average\n"
        "  calculate_macd('NIFTY')                    — MACD 12/26/9\n"
        "  calculate_adx('NIFTY')                     — ADX + DI (trend strength)\n"
        "  calculate_atr('NIFTY')                     — Average True Range (volatility)\n"
        "  analyze_technicals('NIFTY')                — all indicators in one call\n"
        "  Symbols: 'NIFTY','BANKNIFTY','NSE:INFY', or raw yfinance tickers.\n\n"
        "ANALYSIS tools (deterministic trade analysis, no auth needed):\n"
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
        "  get_upcoming_events(days_ahead=7)        — RBI MPC, FOMC, CPI, GDP, NFP schedule\n\n"
        "PORTFOLIO INTELLIGENCE tools (require active session):\n"
        "  get_portfolio_risk_report()       — per-position risk scores + portfolio risk + recommendations\n"
        "  get_portfolio_regime_analysis()   — regime distribution + directional bias across holdings\n"
        "  get_portfolio_exposure_breakdown() — long/short exposure, concentration, diversification\n"
        "  analyze_portfolio([broker])       — unified analytics: sector/broker exposure, networth, P&L, concentration risk\n\n"
        "CATALYST INTELLIGENCE tools (earnings, event risk, no auth needed):\n"
        "  get_earnings_calendar('INFY')     — next earnings date, EPS estimate, dividends, splits\n"
        "  get_event_risk('INFY')            — composite 0-100 event risk: earnings + news + market\n\n"
        "POSITION SIZING tools (portfolio-aware, no auth needed):\n"
        "  size_options_trade('NIFTY', 'LONG', premium=120, stoploss_premium=60, lot_size=50)\n"
        "    — lots, quantity, capital_required; warns when single-position risk > 5%\n"
        "  size_from_recommendation('INFY', capital=100000, risk_percent=1)\n"
        "    — calls recommend_trade() then adds full absolute sizing + log_trade_params\n"
        "    — returns null sizing fields when recommendation is AVOID\n\n"
        "TRADE RECOMMENDATIONS tools (portfolio-aware, no auth needed):\n"
        "  review_open_trades()\n"
        "    — live review of all open journal positions: HOLD / REDUCE / EXIT\n"
        "    — current_price, current_pnl, stoploss_breached, target_reached per position\n"
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
        "BROKER INTELLIGENCE tools (multi-broker unified access):\n"
        "  get_unified_holdings([broker])   — demat holdings from zerodha, indmoney, or both\n"
        "  get_unified_positions([broker])  — open positions from zerodha, indmoney, or both\n"
        "  get_unified_funds([broker])      — available funds from zerodha, indmoney, or both\n"
        "  get_unified_orders([broker])     — today's orders from zerodha, indmoney, or both\n"
        "  get_broker_status()              — authentication status for each configured broker\n"
        "  broker param: 'zerodha' | 'indmoney' | 'all' (default 'all')\n"
        "  INDmoney requires INDSTOCKS_TOKEN env var.\n\n"
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
costs.register(mcp)
mcx.register(mcp)
recommendations.register(mcp)
sizer.register(mcp)
meta_tools.register(mcp)
brokers.register(mcp)
chart.register(mcp)
candles.register(mcp)
chart_patterns.register(mcp)
options_awareness.register(mcp)
market_awareness.register(mcp)
charts.register(mcp)
monitor.register(mcp)

_sse_app = mcp.sse_app()
_http_app = mcp.streamable_http_app()


_UI_DIR = os.path.join(os.path.dirname(__file__), "ui")
_LOGIN_TEMPLATE = open(os.path.join(_UI_DIR, "login.html"), encoding="utf-8").read()
_HOME_TEMPLATE  = open(os.path.join(_UI_DIR, "home.html"),  encoding="utf-8").read()
_TRADE_TEMPLATE = open(os.path.join(_UI_DIR, "trade.html"), encoding="utf-8").read()

_TOOL_COUNT = len(mcp._tool_manager.list_tools())


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


async def _send_json(send, status: int, data: dict, extra_headers: list = []) -> None:
    body = json.dumps(data).encode()
    headers = [[b"content-type", b"application/json"],
               [b"content-length", str(len(body)).encode()]] + extra_headers
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


def _trade_pin_ok(supplied: str) -> bool:
    """Constant-time compare of the supplied PIN against TRADE_PIN.

    The /trade routes are gated ONLY by this PIN — they deliberately do not use
    the MCP OAuth/Bearer flow (see the routes in _app). Returns False if
    TRADE_PIN is unset so the feature is disabled-by-default until configured.
    """
    import hmac
    expected = os.environ.get("TRADE_PIN", "")
    if not expected:
        return False
    return hmac.compare_digest(str(supplied or ""), expected)


def _build_order_from_web(data: dict):
    """Turn the trade page's JSON payload into an OrderRequest.

    Returns (OrderRequest, None) on success or (None, error_message) on bad input.
    Reuses the same validation vocabulary as the Telegram order_parser.

    ``security_id``, if present, is trusted as-is — it means the user picked
    an exact contract from the /trade/symbols autocomplete dropdown, which is
    the only reliable way to identify a specific weekly-options contract
    (index options can share a TRADING_SYMBOL string across several weekly
    expiries in the same month; only security_id is unique per contract — see
    INDmoneyBroker.search_instruments/resolve_security_id). If absent, the
    caller (server.py's /trade/place route) falls back to symbol-text
    resolution, which is ambiguous for those contracts.
    """
    from src.brokers.models import OrderRequest
    from src.telegram_admin.order_parser import _is_derivative_symbol

    symbol = str(data.get("symbol", "")).strip().upper()
    side = str(data.get("side", "")).strip().upper()
    order_type = str(data.get("order_type", "MARKET")).strip().upper()
    product = str(data.get("product", "INTRADAY")).strip().upper()
    exchange = str(data.get("exchange", "NSE")).strip().upper()
    security_id = str(data.get("security_id", "")).strip()
    if not symbol:
        return None, "Symbol is required."
    if side not in ("BUY", "SELL"):
        return None, "Side must be BUY or SELL."
    try:
        qty = int(data.get("quantity"))
    except (TypeError, ValueError):
        return None, "Quantity must be a whole number."
    if qty <= 0:
        return None, "Quantity must be positive."
    if order_type not in ("MARKET", "LIMIT"):
        return None, "Order type must be MARKET or LIMIT."
    if product not in ("CNC", "INTRADAY", "MARGIN"):
        return None, "Product must be CNC, INTRADAY or MARGIN."
    if exchange not in ("NSE", "BSE"):
        return None, "Exchange must be NSE or BSE."
    limit_price = 0.0
    if order_type == "LIMIT":
        try:
            limit_price = float(data.get("limit_price") or 0)
        except (TypeError, ValueError):
            return None, "Invalid limit price."
        if limit_price <= 0:
            return None, "LIMIT orders need a positive price."

    req = OrderRequest(
        security_id=security_id,
        exchange=exchange,
        segment="DERIVATIVE" if _is_derivative_symbol(symbol) else "EQUITY",
        transaction_type=side,
        quantity=qty,
        order_type=order_type,
        product=product,
        limit_price=limit_price,
        symbol=symbol,
    )
    return req, None


async def _is_market_session_open_safe() -> bool:
    """Wraps is_market_session_open() with a conservative fallback.

    A calendar-provider fetch failure here must not silently make a
    closed-market order look "open" (that's exactly the 512
    Internal Server Error bug from INDstocks this check exists to avoid,
    confirmed 2026-07-12) — on error, assume closed so the order gets
    AMO-flagged. Worst case that's an unnecessary AMO flag on a session
    that was actually open; the alternative risks reproducing the bug.
    """
    import asyncio
    from src.market.calendar import is_market_session_open
    try:
        return await asyncio.get_running_loop().run_in_executor(None, is_market_session_open)
    except Exception as exc:
        logging.getLogger(__name__).warning("is_market_session_open() failed, assuming closed: %s", exc)
        return False


_oauth_codes = {}

def _verify_pkce(code_verifier: str, code_challenge: str, method: str) -> bool:
    import hashlib
    import base64
    if method == "S256":
        hashed = hashlib.sha256(code_verifier.encode("utf-8")).digest()
        calculated = base64.urlsafe_b64encode(hashed).decode("utf-8").rstrip("=")
        return calculated == code_challenge
    elif method == "plain" or not method:
        return code_verifier == code_challenge
    return False


def _get_cookie(scope, name: str) -> str | None:
    for key, val in scope.get("headers", []):
        if key == b"cookie":
            for part in val.decode().split(";"):
                k, _, v = part.strip().partition("=")
                if k.strip() == name:
                    return v.strip() or None
    return None


def _render_login(prefill_user_id: str, message: str, oauth_query: str = "") -> str:
    action = f"/login?{oauth_query}" if oauth_query else "/login"
    if oauth_query:
        guest_url = f"/oauth/authorize?{oauth_query}&guest=1"
        guest_btn = (
            f'<a href="{guest_url}" class="guest-btn">'
            "Continue as guest — market data &amp; free tools only"
            "</a>"
        )
    else:
        guest_btn = ""
    return (
        _LOGIN_TEMPLATE
        .replace("{prefill_user_id}", prefill_user_id)
        .replace("{message}", message)
        .replace("{guest_btn}", guest_btn)
        .replace('action="/login"', f'action="{action}"')
    )


async def _handle_login_get(scope, send) -> None:
    prefill = os.environ.get("ZERODHA_USER_ID", "")
    uid_cookie = _get_cookie(scope, "mcp_uid")
    if uid_cookie:
        msg = f'<p class="alert ok">Welcome back, {uid_cookie}. Log in again to refresh your session.</p>'
    elif get_broker().is_authenticated():
        msg = '<p class="alert ok">A session is already active. Log in again to refresh it.</p>'
    else:
        msg = ""
    await _send_html(send, 200, _render_login(prefill, msg))


async def _handle_login_post(scope, receive, send) -> None:
    raw = await _read_body(receive)
    params = urllib.parse.parse_qs(raw.decode(), keep_blank_values=False)
    user_id   = (params.get("user_id",   [""])[0]).strip()
    password  = (params.get("password",  [""])[0]).strip()
    totp_code = (params.get("totp_code", [""])[0]).strip()

    # Parse query parameters from scope (contains redirect_uri, state, code_challenge, code_challenge_method)
    query_str = scope.get("query_string", b"").decode()
    oauth_params = urllib.parse.parse_qs(query_str, keep_blank_values=False)
    redirect_uri = (oauth_params.get("redirect_uri", [""])[0]).strip()
    state = (oauth_params.get("state", [""])[0]).strip()
    code_challenge = (oauth_params.get("code_challenge", [""])[0]).strip()
    code_challenge_method = (oauth_params.get("code_challenge_method", ["S256"])[0]).strip()

    if not (user_id and password and totp_code):
        prefill = os.environ.get("ZERODHA_USER_ID", "")
        msg = '<p class="alert err">All fields are required.</p>'
        await _send_html(send, 400, _render_login(prefill, msg, query_str))
        return

    try:
        broker = get_broker()
        broker.login(user_id=user_id, password=password, totp=totp_code)
    except Exception as exc:
        logger.warning("Browser login failed: %s", exc)
        prefill = os.environ.get("ZERODHA_USER_ID", "")
        msg = f'<p class="alert err">Login failed: {exc}</p>'
        await _send_html(send, 401, _render_login(prefill, msg, query_str))
        return

    # Persist session + generate API key — non-fatal if DB save fails
    enctoken = broker.get_enctoken()
    api_key = None
    if enctoken:
        try:
            session_store.save(user_id, enctoken)
            api_key, _ = api_key_store.get_or_create(user_id)
            # Update the per-user broker cache so check_auth_status() returns true immediately
            get_broker(user_id).set_enctoken(enctoken)
        except Exception as exc:
            logger.warning("Could not persist session/API key for %s: %s", user_id, exc)
    else:
        logger.warning("Login succeeded for %s but broker returned no enctoken — session not persisted", user_id)

    logger.info("Browser login successful for %s", user_id)

    if redirect_uri:
        # Reject non-HTTPS redirect URIs in production (allow localhost for dev)
        parsed_uri = urllib.parse.urlparse(redirect_uri)
        is_local = parsed_uri.hostname in ("localhost", "127.0.0.1")
        if not is_local and parsed_uri.scheme != "https":
            await _send_html(send, 400, "<h1>Invalid redirect_uri — HTTPS required</h1>")
            return

        # Generate temporary auth code
        import secrets
        import time
        code = "auth_" + secrets.token_hex(16)
        _oauth_codes[code] = {
            "user_id": user_id,
            "api_key": api_key,
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
            "expires_at": time.time() + 300
        }
        redirect_url = f"{redirect_uri}?code={code}"
        if state:
            redirect_url += f"&state={urllib.parse.quote(state)}"
        
        await send({
            "type": "http.response.start",
            "status": 302,
            "headers": [[b"location", redirect_url.encode()]]
        })
        await send({"type": "http.response.body", "body": b""})
        return

    key_html = f'<span id="api-key" style="display:none">{api_key}</span>' if api_key else ''
    msg = f'<div class="alert ok">Logged in successfully.{key_html}</div>'
    html = _render_login("", msg).encode()
    cookie = f"mcp_uid={user_id}; Path=/; Max-Age=86400; SameSite=Strict"
    await send({"type": "http.response.start", "status": 200,
                "headers": [[b"content-type", b"text/html; charset=utf-8"],
                            [b"content-length", str(len(html)).encode()],
                            [b"set-cookie", cookie.encode()]]})
    await send({"type": "http.response.body", "body": html})


def _resolve_user(scope) -> str | None:
    """Read Authorization header from headers and resolve to user_id.

    Supports:
    - Bearer <key>
    - Basic <base64(user_id:token)>
    """
    static_key = os.environ.get("MCP_API_KEY", "").strip()

    for name, value in scope.get("headers", []):
        if name.lower() == b"authorization":
            val = value.decode("utf-8", errors="ignore").strip()
            if val.lower().startswith("bearer "):
                key = val[7:].strip()
                if static_key and key == static_key:
                    # Single-user: resolve to the most recent active session
                    uid = session_store.get_active_user_id()
                    return uid or os.environ.get("ZERODHA_USER_ID", "default")
                return api_key_store.lookup(key)
            elif val.lower().startswith("basic "):
                import base64
                try:
                    encoded = val[6:].strip()
                    decoded = base64.b64decode(encoded).decode("utf-8")
                    if ":" not in decoded:
                        continue
                    user_id, password = decoded.split(":", 1)
                    user_id = user_id.strip()
                    password = password.strip()
                    if static_key and password == static_key:
                        uid = session_store.get_active_user_id()
                        active_uid = uid or os.environ.get("ZERODHA_USER_ID", "default")
                        if user_id == active_uid:
                            return active_uid
                    else:
                        resolved_uid = api_key_store.lookup(password)
                        if resolved_uid and resolved_uid == user_id:
                            return resolved_uid
                except Exception as exc:
                    logger.warning("Failed to decode or validate Basic Auth header: %s", exc)
                    continue
    return None


async def app(scope, receive, send):
    # Resolve user from API key header before any route runs
    if scope["type"] == "http":
        uid = _resolve_user(scope)
        # DEV_BYPASS_AUTH=true skips OAuth entirely — never set in production
        if not uid and os.environ.get("DEV_BYPASS_AUTH", "").lower() == "true":
            uid = session_store.get_active_user_id() or os.environ.get("ZERODHA_USER_ID", "dev")
        token = current_user.set(uid)
        path = scope.get("path", "")
        method = scope.get("method", "GET")

        # Trigger OAuth discovery: 401 on unauthenticated stream-open so MCP clients
        # (claude.ai, Claude Desktop) start the OAuth flow. Guest tokens count as auth
        # (uid == "__guest__") so they pass through; personal tools reject them internally.
        is_stream_open = (path == "/sse" and method == "GET") or (path == "/mcp")
        if is_stream_open and not uid:
            base_url = _get_base_url(scope)
            www_auth = f'Bearer resource_metadata="{base_url}/.well-known/oauth-protected-resource"'
            body = b'{"error":"unauthorized","error_description":"Authentication required"}'
            await send({"type": "http.response.start", "status": 401,
                        "headers": [[b"www-authenticate", www_auth.encode()],
                                    [b"content-type", b"application/json"],
                                    [b"content-length", str(len(body)).encode()]]})
            await send({"type": "http.response.body", "body": body})
            current_user.reset(token)
            return

        if path in ("/mcp", "/sse") and uid:
            logger.info("MCP connect: path=%s user_id=%s", path, uid)
        try:
            await _app(scope, receive, send)
        finally:
            current_user.reset(token)
    else:
        await _app(scope, receive, send)


def _get_base_url(scope) -> str:
    public_url = os.environ.get("PUBLIC_URL")
    if public_url:
        return public_url.rstrip("/")
    
    headers = dict(scope.get("headers", []))
    host = headers.get(b"host", b"localhost:8000").decode("utf-8")
    
    proto = "http"
    if headers.get(b"x-forwarded-proto"):
        proto = headers.get(b"x-forwarded-proto").decode("utf-8")
    elif scope.get("scheme"):
        proto = scope.get("scheme")
    elif "443" in host:
        proto = "https"
        
    return f"{proto}://{host}"


async def _app(scope, receive, send):
    if scope["type"] == "http":
        path = scope.get("path", "")
        method = scope.get("method", "GET")

        if path == "/" or path == "":
            html = _HOME_TEMPLATE.replace("{tool_count}", str(_TOOL_COUNT))
            await _send_html(send, 200, html)
            return

        if path == "/health":
            await _send_json(send, 200, {"status": "ok"})
            return

        if path == "/.well-known/oauth-protected-resource":
            base_url = _get_base_url(scope)
            body = json.dumps({
                "resource": f"{base_url}/mcp",
                "authorization_servers": [base_url],
            }).encode()
            await send({"type": "http.response.start", "status": 200,
                        "headers": [[b"content-type", b"application/json"],
                                    [b"content-length", str(len(body)).encode()],
                                    [b"access-control-allow-origin", b"*"]]})
            await send({"type": "http.response.body", "body": body})
            return

        if path == "/.well-known/oauth-authorization-server":
            base_url = _get_base_url(scope)
            body = json.dumps({
                "issuer": base_url,
                "authorization_endpoint": f"{base_url}/oauth/authorize",
                "token_endpoint": f"{base_url}/oauth/token",
                "registration_endpoint": f"{base_url}/oauth/register",
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code"],
                "token_endpoint_auth_methods_supported": ["none", "client_secret_post", "client_secret_basic"],
                "code_challenge_methods_supported": ["S256"],
            }).encode()
            await send({"type": "http.response.start", "status": 200,
                        "headers": [[b"content-type", b"application/json"],
                                    [b"content-length", str(len(body)).encode()],
                                    [b"access-control-allow-origin", b"*"]]})
            await send({"type": "http.response.body", "body": body})
            return

        if path == "/oauth/register" and method == "POST":
            import secrets as _secrets
            raw = await _read_body(receive)
            try:
                meta = json.loads(raw.decode()) if raw else {}
            except Exception:
                meta = {}
            client_id = meta.get("client_id") or "client_" + _secrets.token_hex(8)
            body = json.dumps({
                "client_id": client_id,
                "client_secret": None,
                "token_endpoint_auth_method": "none",
                "grant_types": ["authorization_code"],
                "response_types": ["code"],
                "redirect_uris": meta.get("redirect_uris", []),
            }).encode()
            await send({"type": "http.response.start", "status": 201,
                        "headers": [[b"content-type", b"application/json"],
                                    [b"content-length", str(len(body)).encode()],
                                    [b"access-control-allow-origin", b"*"]]})
            await send({"type": "http.response.body", "body": body})
            return

        if path == "/oauth/register" and method == "OPTIONS":
            await send({"type": "http.response.start", "status": 204,
                        "headers": [[b"access-control-allow-origin", b"*"],
                                    [b"access-control-allow-methods", b"POST,OPTIONS"],
                                    [b"access-control-allow-headers", b"content-type"]]})
            await send({"type": "http.response.body", "body": b""})
            return

        if path == "/oauth/authorize" and method == "GET":
            query_str = scope.get("query_string", b"").decode()
            oauth_params = urllib.parse.parse_qs(query_str, keep_blank_values=False)
            redirect_uri = (oauth_params.get("redirect_uri", [""])[0]).strip()
            state = (oauth_params.get("state", [""])[0]).strip()
            code_challenge = (oauth_params.get("code_challenge", [""])[0]).strip()
            code_challenge_method = (oauth_params.get("code_challenge_method", ["S256"])[0]).strip()

            # Guest flow: user clicked "Continue as guest" — issue a limited token
            if oauth_params.get("guest", [""])[0] == "1" and redirect_uri:
                import secrets as _s, time as _t
                guest_key, _ = api_key_store.get_or_create("__guest__")
                code = "auth_" + _s.token_hex(16)
                _oauth_codes[code] = {
                    "user_id": "__guest__",
                    "api_key": guest_key,
                    "code_challenge": code_challenge,
                    "code_challenge_method": code_challenge_method,
                    "expires_at": _t.time() + 300,
                }
                redirect_url = f"{redirect_uri}?code={code}"
                if state:
                    redirect_url += f"&state={urllib.parse.quote(state)}"
                await send({"type": "http.response.start", "status": 302,
                            "headers": [[b"location", redirect_url.encode()]]})
                await send({"type": "http.response.body", "body": b""})
                logger.info("OAuth guest token issued")
                return

            # If already logged in (cookie present + session in DB), skip login form
            uid_cookie = _get_cookie(scope, "mcp_uid")
            if uid_cookie and redirect_uri:
                enctoken = session_store.load(uid_cookie)
                if enctoken:
                    import secrets as _s, time as _t
                    api_key, _ = api_key_store.get_or_create(uid_cookie)
                    code = "auth_" + _s.token_hex(16)
                    _oauth_codes[code] = {
                        "user_id": uid_cookie,
                        "api_key": api_key,
                        "code_challenge": code_challenge,
                        "code_challenge_method": code_challenge_method,
                        "expires_at": _t.time() + 300,
                    }
                    redirect_url = f"{redirect_uri}?code={code}"
                    if state:
                        redirect_url += f"&state={urllib.parse.quote(state)}"
                    await send({"type": "http.response.start", "status": 302,
                                "headers": [[b"location", redirect_url.encode()]]})
                    await send({"type": "http.response.body", "body": b""})
                    logger.info("OAuth auto-authorized for %s via existing session", uid_cookie)
                    return

            prefill = os.environ.get("ZERODHA_USER_ID", "")
            msg = ""
            await _send_html(send, 200, _render_login(prefill, msg, query_str))
            return

        if path == "/oauth/token" and method == "POST":
            raw = await _read_body(receive)
            params = {}
            try:
                params = json.loads(raw.decode())
            except Exception:
                parsed = urllib.parse.parse_qs(raw.decode(), keep_blank_values=False)
                params = {k: v[0] for k, v in parsed.items()}

            _cors = [[b"access-control-allow-origin", b"*"],
                     [b"access-control-allow-headers", b"content-type,authorization"]]

            grant_type = params.get("grant_type", "").strip()
            if grant_type and grant_type != "authorization_code":
                await _send_json(send, 400, {"error": "unsupported_grant_type"})
                return

            code = params.get("code", "").strip()
            code_verifier = params.get("code_verifier", "").strip()

            import time
            if not code or code not in _oauth_codes:
                await _send_json(send, 400, {"error": "invalid_grant", "error_description": "Invalid authorization code."})
                return

            code_data = _oauth_codes[code]
            if time.time() > code_data["expires_at"]:
                _oauth_codes.pop(code, None)
                await _send_json(send, 400, {"error": "invalid_grant", "error_description": "Authorization code expired."})
                return

            challenge = code_data.get("code_challenge")
            challenge_method = code_data.get("code_challenge_method", "S256")
            if challenge:
                if not code_verifier or not _verify_pkce(code_verifier, challenge, challenge_method):
                    await _send_json(send, 400, {"error": "invalid_grant", "error_description": "PKCE verification failed."})
                    return

            _oauth_codes.pop(code, None)
            body = json.dumps({
                "access_token": code_data["api_key"],
                "token_type": "bearer",
                "expires_in": 86400,
            }).encode()
            await send({"type": "http.response.start", "status": 200,
                        "headers": [[b"content-type", b"application/json"],
                                    [b"content-length", str(len(body)).encode()]] + _cors})
            await send({"type": "http.response.body", "body": body})
            return

        if path == "/oauth/token" and method == "OPTIONS":
            # CORS preflight for browser-based OAuth clients
            await send({"type": "http.response.start", "status": 204,
                        "headers": [[b"access-control-allow-origin", b"*"],
                                    [b"access-control-allow-methods", b"POST,OPTIONS"],
                                    [b"access-control-allow-headers", b"content-type,authorization"],
                                    [b"access-control-max-age", b"86400"]]})
            await send({"type": "http.response.body", "body": b""})
            return

        if path == "/login" and method == "GET":
            await _handle_login_get(scope, send)
            return

        if path == "/login" and method == "POST":
            await _handle_login_post(scope, receive, send)
            return

        if path == "/guest-token" and method == "GET":
            guest_key, _ = api_key_store.get_or_create("__guest__")
            await _send_json(send, 200, {"token": guest_key, "type": "bearer"})
            return

        if path == "/auth/status":
            uid = current_user.get()  # only set if request carries a valid Bearer token
            if uid:
                broker = get_broker(uid)
                await _send_json(send, 200, {
                    "authenticated": broker.is_authenticated(),
                    "backend": type(broker).__name__,
                    "user_id": uid,
                })
            else:
                await _send_json(send, 200, {
                    "authenticated": False,
                    "user_id": None,
                })
            return

        if path == "/logout" and method == "POST":
            # Accept Bearer token (MCP client) or mcp_uid cookie (browser)
            uid = current_user.get() or _get_cookie(scope, "mcp_uid")
            if not uid or uid == "__guest__":
                await _send_json(send, 401, {"error": "unauthorized"})
                return
            session_store.delete(uid)
            api_key_store.delete(uid)
            from src.broker import reset_broker
            reset_broker(uid)
            get_broker().clear_enctoken()
            logger.info("Logout: %s", uid)
            await _send_json(send, 200, {"logged_out": True, "user_id": uid},
                             extra_headers=[[b"set-cookie", b"mcp_uid=; Path=/; Max-Age=0; SameSite=Strict"]])
            return

        # ── Mobile order-placement web app (Phase 23) ──────────────────────
        # PIN-gated, independent of the MCP OAuth/Bearer flow. The GET serves
        # the form; /trade/preview validates + echoes a confirm summary (no
        # order placed); /trade/place is the only route that fires an order,
        # so every order requires an explicit second request ("confirm every
        # order"). These sit before the MCP fall-through and never touch
        # current_user — TRADE_PIN is the sole gate.
        if path == "/trade" and method == "GET":
            await _send_html(send, 200, _TRADE_TEMPLATE)
            return

        if path == "/trade/symbols" and method == "GET":
            qs = urllib.parse.parse_qs(scope.get("query_string", b"").decode())
            pin = (qs.get("pin", [""])[0]).strip()
            query = (qs.get("q", [""])[0]).strip()
            segment = (qs.get("segment", [""])[0]).strip() or None
            if not _trade_pin_ok(pin):
                await _send_json(send, 403, {"error": "invalid PIN"})
                return
            if len(query) < 2:
                await _send_json(send, 200, {"results": []})
                return
            from src.execution.service import search_symbols
            try:
                results = await search_symbols(query, segment=segment)
            except Exception as exc:
                await _send_json(send, 502, {"error": f"symbol search failed: {exc}"})
                return
            await _send_json(send, 200, {"results": results})
            return

        if path == "/trade/preview" and method == "POST":
            raw = await _read_body(receive)
            try:
                data = json.loads(raw.decode()) if raw else {}
            except Exception:
                await _send_json(send, 400, {"error": "invalid JSON"})
                return
            if not _trade_pin_ok(data.get("pin", "")):
                await _send_json(send, 403, {"error": "invalid PIN"})
                return
            req, err = _build_order_from_web(data)
            if err:
                await _send_json(send, 400, {"error": err})
                return
            session_open = await _is_market_session_open_safe()
            price = ("at market (auto-LIMIT @ live price)" if req.order_type == "MARKET"
                     else f"LIMIT @ ₹{req.limit_price:g}")
            summary_html = (
                f"<b>{req.transaction_type} {req.symbol}</b><br>"
                f"Qty: <b>{req.quantity}</b><br>{price}<br>"
                f"Product: {req.product} &nbsp;|&nbsp; {req.exchange} {req.segment}"
            )
            if not session_open:
                summary_html += (
                    "<br><b>Market is closed</b> — this will be placed as an "
                    "AMO (After Market Order), queued for the next session."
                )
            await _send_json(send, 200, {"ok": True, "summary_html": summary_html})
            return

        if path == "/trade/place" and method == "POST":
            raw = await _read_body(receive)
            try:
                data = json.loads(raw.decode()) if raw else {}
            except Exception:
                await _send_json(send, 400, {"error": "invalid JSON"})
                return
            if not _trade_pin_ok(data.get("pin", "")):
                await _send_json(send, 403, {"error": "invalid PIN"})
                return
            req, err = _build_order_from_web(data)
            if err:
                await _send_json(send, 400, {"error": err})
                return
            session_open = await _is_market_session_open_safe()
            if not session_open:
                if req.is_smart_order:
                    # AMO support for INDstocks' /smart/order (SL/target leg)
                    # endpoint isn't confirmed against their docs — only the
                    # plain /order endpoint's is_amo behavior is (2026-07-12).
                    # Reject rather than guess at an unverified API contract;
                    # today the web form never sets SL/target fields anyway,
                    # so this only matters if that changes later.
                    await _send_json(send, 400, {
                        "error": "Market is closed. SL/target orders can't be placed "
                                 "after hours (AMO support for that order type isn't "
                                 "confirmed) — place a plain order to queue it as AMO, "
                                 "or try again during market hours."})
                    return
                req.is_amo = True
                req.validity = "DAY"
            from src.execution.service import submit_order, resolve_symbol
            # If the client already sent a security_id (user picked an exact
            # contract from the /trade/symbols dropdown), trust it — re-resolving
            # by symbol text is ambiguous for weekly index options that share a
            # TRADING_SYMBOL string across several expiries in the same month.
            # Only fall back to text resolution when no id was supplied (e.g.
            # user typed a symbol without picking from the dropdown).
            if not req.security_id:
                try:
                    sec_id = await resolve_symbol(req.symbol, exchange=req.exchange, segment=req.segment)
                except Exception as exc:
                    await _send_json(send, 502, {"error": f"symbol resolution failed: {exc}"})
                    return
                if not sec_id:
                    await _send_json(send, 400, {
                        "error": f"Symbol '{req.symbol}' not found in {req.exchange} {req.segment} instruments."})
                    return
                req.security_id = sec_id
            result = await submit_order(req, source="web", user_id=os.environ.get("ZERODHA_USER_ID"))
            status = 200 if result.get("status") == "ok" else 502
            await _send_json(send, status, result)
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

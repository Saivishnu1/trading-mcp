import os
import logging
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from src.broker import get_broker
from src.tools import auth, portfolio, market, instruments

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

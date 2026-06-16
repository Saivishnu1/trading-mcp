# Zerodha Personal MCP Server

Remote MCP server for your personal Zerodha account — **no Kite Connect subscription required**.

## How it works

| Layer | Implementation | Source |
|-------|---------------|--------|
| Auth + portfolio | Direct HTTPS to `kite.zerodha.com` (enctoken) | Your personal account |
| Live NSE quotes | `jugaad-data` NSELive | NSE public feed |
| Historical data | Yahoo Finance (`yfinance`) | Free |
| Instruments | NSE public EQUITY_L.csv | Free |
| Broker fallback | `jugaad-trader` (set `BROKER_BACKEND=jugaad`) | — |

## Quickstart

```bash
cp .env.example .env
# Fill in ZERODHA_USER_ID, ZERODHA_PASSWORD, ZERODHA_TOTP_SECRET

docker compose up -d
```

MCP SSE endpoint: `http://your-host:8000/sse`

## Authentication

Zerodha uses a daily session token (enctoken) that expires at ~07:30 IST.
The server persists it to `.session.json` and reloads it on restart.

**One-time login** (call from Claude or any MCP client):
```
zerodha_login(user_id="ZK1234", password="...", totp_code="123456")
```

If you stored `ZERODHA_TOTP_SECRET` in `.env`, pass `totp_secret` instead of
`totp_code` and the server generates the code automatically — useful for
unattended servers with a daily cron restart.

## Add to Claude Desktop

```json
{
  "mcpServers": {
    "zerodha": {
      "url": "http://your-host:8000/sse"
    }
  }
}
```

## MCP Tools

### Auth (no session needed to call login)
| Tool | Description |
|------|-------------|
| `zerodha_login` | Log in with user_id + password + TOTP |
| `get_profile` | Authenticated user's profile |
| `check_auth_status` | Session active? Which backend? |

### Portfolio (session required)
| Tool | Description |
|------|-------------|
| `get_holdings` | Long-term demat holdings |
| `get_positions` | Intraday / net positions |
| `get_margins` | Available funds (equity / commodity) |

### Market data (no session needed)
| Tool | Description |
|------|-------------|
| `get_quote(['NSE:INFY'])` | Full quote with OHLC, change, volume |
| `get_ohlc(['NSE:TCS'])` | OHLC snapshot |
| `get_ltp(['NSE:INFY'])` | Last traded price only |
| `get_historical_data('NSE:INFY','2024-01-01','2024-12-31','1d')` | OHLCV candles |

Symbol format: `EXCHANGE:SYMBOL` — e.g. `NSE:INFY`, `BSE:RELIANCE`, `NSE:NIFTY 50`.

`get_historical_data` intervals: `1m 2m 5m 15m 30m 60m 1h 1d 5d 1wk 1mo 3mo`
(Kite-style aliases like `"day"`, `"minute"` also accepted).

### Instruments (no session needed)
| Tool | Description |
|------|-------------|
| `search_instruments('Infosys')` | Symbol / name search (NSE equity list) |
| `get_instruments('NSE')` | Full NSE equity list |
| `invalidate_instruments_cache()` | Force reload from NSE CSV |

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ZERODHA_USER_ID` | Yes | Your Zerodha client ID |
| `ZERODHA_PASSWORD` | Yes | Your trading password |
| `ZERODHA_TOTP_SECRET` | No | Base32 TOTP secret for auto-login |
| `BROKER_BACKEND` | No | `zerodha_web` (default) or `jugaad` |
| `SESSION_FILE` | No | Enctoken file path (default `.session.json`) |
| `HOST` | No | Bind host (default `0.0.0.0`) |
| `PORT` | No | Bind port (default `8000`) |
| `LOG_LEVEL` | No | `INFO` (default) / `DEBUG` / `WARNING` |

## Switching broker backends

If Zerodha changes their internal web API and the default client breaks:

```env
BROKER_BACKEND=jugaad
```

`jugaad-trader` is installed automatically and provides an identical interface —
no MCP tool changes needed.

## Limitations vs Kite Connect

- **No order placement** — Zerodha blocks programmatic orders via web sessions.
  Use the Kite app, or subscribe to Kite Connect for order APIs only.
- **No F&O/MCX instrument dump** — only NSE equity list available for free.
- **No WebSocket ticker** — poll `get_ltp()` for price updates.
- **Intraday history capped at 60 days** — Yahoo Finance limitation for `<1d` intervals.

See [MIGRATION.md](MIGRATION.md) for a full comparison.

## Deploy

**Railway:** `railway up` — Dockerfile is auto-detected.

**Render:** Docker runtime, set env vars in the dashboard.

**VPS:** `docker compose up -d`

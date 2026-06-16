# Zerodha Personal MCP Server

A remote [Model Context Protocol](https://modelcontextprotocol.io) server for your personal Zerodha account.
Gives Claude (or any MCP client) live access to your portfolio, NSE market data, and instrument search —
**no paid Kite Connect subscription required**.

---

## Table of contents

1. [How it works](#how-it-works)
2. [Prerequisites](#prerequisites)
3. [Getting your credentials](#getting-your-credentials)
   - [ZERODHA\_USER\_ID](#zerodha_user_id)
   - [ZERODHA\_PASSWORD](#zerodha_password)
   - [ZERODHA\_TOTP\_SECRET](#zerodha_totp_secret)
4. [Setup](#setup)
   - [Clone and configure](#1-clone-and-configure)
   - [Run with Docker](#2-run-with-docker)
   - [Run locally with uv](#run-locally-with-uv-no-docker)
5. [First login](#first-login)
6. [Add to Claude](#add-to-claude)
7. [MCP tools reference](#mcp-tools-reference)
8. [Environment variables](#environment-variables)
9. [Session lifetime and daily re-login](#session-lifetime-and-daily-re-login)
10. [Switching broker backends](#switching-broker-backends)
11. [Deploying remotely](#deploying-remotely)
12. [Limitations](#limitations)

---

## How it works

| Layer | What runs | Data source |
|-------|-----------|-------------|
| Auth + portfolio | Direct HTTPS to `kite.zerodha.com` using `enctoken` | Your personal Zerodha account |
| Live NSE quotes | `jugaad-data` NSELive | NSE public market feed (free) |
| Historical OHLCV | Yahoo Finance (`yfinance`) | Free, no account needed |
| Instrument search | NSE public `EQUITY_L.csv` | Free |
| Broker fallback | `jugaad-trader` (opt-in via env var) | Reverse-engineered Kite web client |

The server exposes all functionality as MCP tools over **SSE transport**, so any MCP-compatible client
(Claude Desktop, Claude Code, etc.) can connect to it over the network.

---

## Prerequisites

- A **Zerodha trading account** (free, at [zerodha.com](https://zerodha.com))
- **2-Factor Authentication (TOTP)** enabled on your Zerodha account
- Docker + Docker Compose **or** Python 3.12+ with [uv](https://github.com/astral-sh/uv)

---

## Getting your credentials

You need three values from your Zerodha account. Here is exactly where to find each one.

---

### `ZERODHA_USER_ID`

This is your **Zerodha Client ID** — a 6-character alphanumeric code printed on all Zerodha
communications (e.g. `ZK1234`, `AB5678`).

**Where to find it:**

1. Open [kite.zerodha.com](https://kite.zerodha.com) in your browser and log in.
2. Click your **name / avatar** in the top-right corner.
3. Select **My Profile**.
4. Your Client ID appears at the top of the profile page under your name.

Alternatively, check any email from Zerodha — it appears in the subject line and footer of every
account-related email as *"Client ID: ZK1234"*.

```env
ZERODHA_USER_ID=ZK1234
```

---

### `ZERODHA_PASSWORD`

This is the **password you use to log in to Kite** (the Zerodha trading platform).

It is the same password you type on the [kite.zerodha.com](https://kite.zerodha.com) login page —
**not** your Zerodha account PIN, not your UPI PIN, not your bank password.

> **Tip:** If you have forgotten it, reset it at  
> `Console → My Account → Password & Security → Reset Login Password`  
> ([console.zerodha.com](https://console.zerodha.com))

```env
ZERODHA_PASSWORD=your_kite_login_password
```

---

### `ZERODHA_TOTP_SECRET`

This is the **base32 secret key** behind your Zerodha TOTP authenticator. It is the raw key that
Google Authenticator / Authy encodes as a QR code. Providing this lets the server generate the
6-digit code automatically — useful for unattended/remote deployments.

> If you prefer to type the 6-digit code manually each time instead, leave `ZERODHA_TOTP_SECRET`
> blank and pass `totp_code="123456"` when calling `zerodha_login()`.

#### How to get your TOTP secret (step by step)

Zerodha shows you this secret **only once** — when you first set up TOTP.
If you have already set up TOTP and did not save the secret, you must reset 2FA to get a new one.

**Option A — Setting up TOTP for the first time**

1. Go to [console.zerodha.com](https://console.zerodha.com) and log in.
2. Navigate to **My Account → Password & Security**.
3. Under the **Two-factor authentication** section, click **Set up TOTP**.
4. Zerodha displays a **QR code** and, below it, a text string that says something like:
   ```
   Can't scan? Enter this key manually: JBSWY3DPEHPK3PXP
   ```
   That `JBSWY3DPEHPK3PXP` is your **TOTP secret**. Copy it exactly.
5. Scan the QR code with Google Authenticator / Authy to register it.
6. Enter the 6-digit code from your authenticator app to confirm setup.
7. Paste the secret into your `.env`:
   ```env
   ZERODHA_TOTP_SECRET=JBSWY3DPEHPK3PXP
   ```

**Option B — You already have TOTP set up but never saved the secret**

You need to reset 2FA to get a new secret:

1. Go to [console.zerodha.com](https://console.zerodha.com) → **My Account → Password & Security**.
2. Under **Two-factor authentication**, click **Reset TOTP**.
3. Zerodha will send a verification to your registered email/mobile.
4. After verifying, a new QR code and secret are shown — follow steps 4–7 from Option A above.

> **Security note:** Treat the TOTP secret like a password. Anyone with it can generate valid
> one-time codes for your account. Store it only in your `.env` file (which is git-ignored) or
> in your hosting platform's secret manager.

```env
ZERODHA_TOTP_SECRET=YOUR_BASE32_SECRET_HERE
```

---

## Setup

### 1. Clone and configure

```bash
git clone https://github.com/Saivishnu1/trading-mcp.git
cd trading-mcp
cp .env.example .env
```

Open `.env` and fill in your credentials:

```env
ZERODHA_USER_ID=ZK1234
ZERODHA_PASSWORD=your_kite_password
ZERODHA_TOTP_SECRET=YOUR_BASE32_TOTP_SECRET

BROKER_BACKEND=zerodha_web
SESSION_FILE=.session.json
HOST=0.0.0.0
PORT=8000
LOG_LEVEL=INFO
```

---

### 2. Run with Docker

```bash
docker compose up -d
```

The server starts on port `8000`. Check it is running:

```bash
docker compose logs -f
```

You should see:

```
INFO:     Started server process
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000
```

**Stop the server:**

```bash
docker compose down
```

---

### Run locally with uv (no Docker)

```bash
# Install uv if you don't have it
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies
uv sync

# Run
uv run zerodha-mcp
```

---

## First login

Market data tools work immediately without authentication. Portfolio tools (`get_holdings`,
`get_positions`, `get_margins`) require a live Zerodha session.

### Option A — Login via Claude (recommended)

Once the server is connected to Claude, just ask:

> *"Log in to Zerodha"*

Claude will call `zerodha_login()` automatically. If `ZERODHA_TOTP_SECRET` is set in `.env`,
no further input is needed. If not, Claude will ask you for the current 6-digit code from your
authenticator app.

### Option B — Login by calling the tool directly

From any MCP client, call:

```
zerodha_login(
  user_id="ZK1234",
  password="your_password",
  totp_code="123456"          ← current 6-digit code from your authenticator
)
```

Or, if you saved `ZERODHA_TOTP_SECRET`:

```
zerodha_login(
  user_id="ZK1234",
  password="your_password",
  totp_secret="YOUR_BASE32_SECRET"   ← server generates the code
)
```

A successful login returns:

```json
{
  "status": "authenticated",
  "backend": "ZerodhaWebClient",
  "user_id": "ZK1234",
  "user_name": "Sai Vishnu",
  "email": "you@example.com"
}
```

The session token is saved to `.session.json` and reloaded automatically on the next server start.

### Check session status

```
check_auth_status()
```

```json
{
  "authenticated": true,
  "backend": "ZerodhaWebClient"
}
```

---

## Add to Claude

### Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or
`%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "zerodha": {
      "url": "http://localhost:8000/sse"
    }
  }
}
```

Replace `localhost` with your server's IP or hostname for remote deployments.
Restart Claude Desktop after saving.

### Claude Code (CLI)

```bash
claude mcp add zerodha --url http://localhost:8000/sse
```

---

## MCP tools reference

### Authentication tools

| Tool | Auth needed | Description |
|------|-------------|-------------|
| `zerodha_login(user_id, password, totp_code?, totp_secret?)` | No | Log in to Zerodha. Pass either `totp_code` (6-digit) or `totp_secret` (base32). |
| `get_profile()` | Yes | Returns your name, email, broker, and enabled exchanges. |
| `check_auth_status()` | No | Returns `{authenticated, backend}` without an API call. |

### Portfolio tools

All portfolio tools require an active session. Call `zerodha_login()` first if `check_auth_status()` returns `false`.

| Tool | Description | Key fields returned |
|------|-------------|---------------------|
| `get_holdings()` | Your long-term demat holdings | `tradingsymbol`, `quantity`, `average_price`, `last_price`, `pnl` |
| `get_positions()` | Intraday and carry-forward positions | `net[]` and `day[]` lists with `pnl`, `quantity`, `buy_price` |
| `get_margins(segment?)` | Available fund margins | `net`, `available.cash`, `utilised.debits` |

`segment` is `"equity"` (default) or `"commodity"`.

### Market data tools

No authentication required. Data is sourced from NSE public feed and Yahoo Finance.

| Tool | Arguments | Description |
|------|-----------|-------------|
| `get_quote(instruments)` | `["NSE:INFY", "BSE:RELIANCE"]` | Full quote: last price, OHLC, change, volume |
| `get_ohlc(instruments)` | `["NSE:TCS", "NSE:WIPRO"]` | Today's OHLC snapshot |
| `get_ltp(instruments)` | `["NSE:INFY", "NSE:NIFTY 50"]` | Last traded price only (fastest) |
| `get_historical_data(symbol, from_date, to_date, interval)` | See below | Historical OHLCV candles |

**Symbol format:**

| What you want | Symbol string |
|---------------|--------------|
| NSE stock | `NSE:INFY` |
| BSE stock | `BSE:RELIANCE` |
| Nifty 50 index | `NSE:NIFTY 50` |
| Bank Nifty | `NSE:NIFTY BANK` |
| Sensex | `NSE:SENSEX` |
| Raw yfinance ticker | `INFY.NS`, `^NSEI` |

**Historical data intervals:**

| Interval string | Candle size | Max history |
|----------------|-------------|-------------|
| `1m` | 1 minute | 7 days |
| `2m`, `5m`, `15m`, `30m`, `60m`, `90m` | Intraday | 60 days |
| `1h` | 1 hour | 730 days |
| `1d` | Daily | Full history |
| `5d`, `1wk`, `1mo`, `3mo` | Weekly / monthly | Full history |

Kite-style aliases (`"minute"`, `"5minute"`, `"day"`, etc.) are also accepted.

**Example:**

```
get_historical_data(
  symbol="NSE:INFY",
  from_date="2024-01-01",
  to_date="2024-12-31",
  interval="1d"
)
```

### Instrument tools

| Tool | Arguments | Description |
|------|-----------|-------------|
| `search_instruments(query, exchange?, limit?)` | `("Infosys", "NSE", 20)` | Search by name or symbol. Uses cached NSE equity list. |
| `get_instruments(exchange?)` | `("NSE")` | Full NSE equity list (~2000 rows). |
| `invalidate_instruments_cache()` | — | Clear cache; reloads from NSE CSV on next call. |

---

## Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ZERODHA_USER_ID` | **Yes** | — | Your Zerodha client ID (e.g. `ZK1234`) |
| `ZERODHA_PASSWORD` | **Yes** | — | Your Kite login password |
| `ZERODHA_TOTP_SECRET` | No | — | Base32 TOTP secret for automatic code generation |
| `BROKER_BACKEND` | No | `zerodha_web` | `zerodha_web` (primary) or `jugaad` (fallback) |
| `SESSION_FILE` | No | `.session.json` | Where the enctoken is persisted between restarts |
| `HOST` | No | `0.0.0.0` | Server bind address |
| `PORT` | No | `8000` | Server port |
| `LOG_LEVEL` | No | `INFO` | `DEBUG`, `INFO`, `WARNING`, or `ERROR` |

---

## Session lifetime and daily re-login

Zerodha's `enctoken` (the session token) **expires every day at approximately 07:30 IST**
when Zerodha resets all active sessions for their end-of-day processing.

This means:
- The server saves the token to `.session.json` and reloads it on restart.
- After 07:30 IST, portfolio tools will return `401 Unauthorized` until you log in again.
- Market data tools (`get_quote`, `get_ltp`, `get_historical_data`) are **not affected** — they
  never need a Zerodha session.

### Automating daily re-login

If `ZERODHA_TOTP_SECRET` is set in your `.env`, you can automate re-login with a cron job that
restarts the container every morning after the reset:

```bash
# Restart the container at 07:45 IST (02:15 UTC) every day
# Add to crontab: crontab -e
15 2 * * * docker compose -f /path/to/trading-mcp/docker-compose.yml restart
```

On startup, the server auto-calls `zerodha_login()` using the credentials in `.env` if a valid
`ZERODHA_TOTP_SECRET` is present. No manual intervention needed.

> **Alternative:** Ask Claude to log you back in each morning — it takes one message.

---

## Switching broker backends

The server has two broker implementations behind an abstract interface. Switching does not change
any MCP tool behaviour.

| Backend | When to use |
|---------|-------------|
| `zerodha_web` (default) | Direct `httpx` calls to `kite.zerodha.com`. Fastest, no extra deps. |
| `jugaad` | If Zerodha changes their internal web API and the primary client breaks. Uses `jugaad-trader`. |

To switch:

```env
# .env
BROKER_BACKEND=jugaad
```

Restart the server. Switch back by setting `BROKER_BACKEND=zerodha_web` or removing the variable.

---

## Deploying remotely

### Railway

```bash
railway login
railway init
railway up
```

Set environment variables in the Railway dashboard under **Variables**.
The `Dockerfile` is auto-detected.

### Render

1. Create a new **Web Service** in the Render dashboard.
2. Connect this GitHub repo.
3. Set **Runtime** to `Docker`.
4. Add all required environment variables under **Environment**.
5. Set **Port** to `8000`.

### Any VPS (Ubuntu/Debian)

```bash
# Install Docker
curl -fsSL https://get.docker.com | sh

# Clone and configure
git clone https://github.com/Saivishnu1/trading-mcp.git
cd trading-mcp
cp .env.example .env
nano .env   # fill in your credentials

# Start
docker compose up -d

# (optional) open firewall port
ufw allow 8000
```

Your MCP endpoint is then: `http://<your-server-ip>:8000/sse`

---

## Limitations

| Feature | Status | Alternative |
|---------|--------|-------------|
| Order placement | Not available | Zerodha blocks programmatic orders via web sessions. Use the Kite app. |
| F&O / MCX instrument dump | Not available | NSE equity list only. Search by symbol works for most lookups. |
| Real-time WebSocket ticker | Not available | Poll `get_ltp()` every few seconds for price updates. |
| Intraday history older than 60 days | Not available | Use `interval="1d"` for full daily history going back years. |
| BSE instrument list | Not available | Use `search_instruments(query, exchange="BSE")` or yfinance tickers directly. |

See [MIGRATION.md](MIGRATION.md) for a detailed comparison with the Kite Connect paid API.

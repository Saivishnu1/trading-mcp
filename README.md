# Zerodha Personal MCP Server

A remote [Model Context Protocol](https://modelcontextprotocol.io) server for your personal Zerodha account.
Gives Claude (or any MCP client) live access to your portfolio, NSE market data, technical analysis,
trade planning, options analytics, journal, and trading intelligence —
**no paid Kite Connect subscription required**.

> **69 tools across 18 domains.** All responses are wrapped with a trust metadata envelope
> that labels data type (FACT / INDICATOR / INTERPRETATION), validation status, data quality,
> and market hours. Analysis tools embed Phase 20A and Phase 21 research findings directly
> in their docstrings so Claude cannot mistake structural descriptors for directional signals.

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
6. [Add to your MCP client](#add-to-your-mcp-client)
7. [MCP tools reference](#mcp-tools-reference)
8. [Tool response format](#tool-response-format)
9. [Environment variables](#environment-variables)
10. [Session lifetime and daily re-login](#session-lifetime-and-daily-re-login)
11. [Switching broker backends](#switching-broker-backends)
12. [Deploying remotely](#deploying-remotely)
13. [Research findings](#research-findings)
14. [Limitations](#limitations)

---

## How it works

| Layer | What runs | Data source |
|-------|-----------|-------------|
| Auth + portfolio | Direct HTTPS to `kite.zerodha.com` using `enctoken` | Your personal Zerodha account |
| Live NSE quotes | `jugaad-data` NSELive | NSE public market feed (free) |
| Historical OHLCV | Yahoo Finance (`yfinance`) | Free, no account needed |
| Instrument search | NSE public `EQUITY_L.csv` | Free |
| Options chain | `jugaad-data` NSELive | NSE public options data |
| Broker fallback | `jugaad-trader` (opt-in via env var) | Reverse-engineered Kite web client |

The server exposes all functionality as MCP tools over **Streamable HTTP** (`/mcp`) and **SSE** (`/sse`),
so any MCP-compatible client (Claude Desktop, Claude Code, claude.ai web connector, etc.) can connect.

---

## Prerequisites

- A **Zerodha trading account** (free, at [zerodha.com](https://zerodha.com))
- **2-Factor Authentication (TOTP)** enabled on your Zerodha account
- Docker + Docker Compose **or** Python 3.12+ with [uv](https://github.com/astral-sh/uv)

> **Using the hosted Railway deployment?** No env vars, Docker, or credentials setup needed.
> Visit `https://zerodha-mcp-production.up.railway.app`, log in through the browser UI,
> and connect your AI client. Skip to [Add to your MCP client](#add-to-your-mcp-client).

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

> If `ZERODHA_TOTP_SECRET` is not set, you will be prompted for the 6-digit code on the
> `/login` browser page each time you log in.

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

## Connecting — guest vs full login

The server has two access tiers:

| Tier | Who | How | Tools available |
|------|-----|-----|-----------------|
| **Guest** | Anyone | Click "Continue as guest" on the OAuth login page | 50+ free tools: market data, options, technicals, dashboards, analysis |
| **Full login** | Account owner | Enter Zerodha credentials on the OAuth login page | All 69 tools including portfolio, journal, recommendations |

**Market data tools work immediately — no login required.**
Portfolio tools (`get_holdings`, `get_positions`, `get_margins`), journal, and recommendations
require a full Zerodha login.

> **Security design:** Credentials never pass through the agent. The `zerodha_login()` MCP tool
> takes no parameters — it returns a URL. You open the URL in your browser and enter credentials
> directly into the server's login page. Nothing sensitive appears in agent context, tool logs,
> or MCP traffic.

### How the login page works

When you (or an MCP client) connect to `/mcp` or `/sse` without a token, the server returns
a `401` response with `WWW-Authenticate: Bearer resource_metadata=...`. MCP clients that
support OAuth (claude.ai, Claude Desktop) automatically open a login popup.

The `/oauth/authorize` page shows:
- A **Zerodha login form** (Client ID + password + TOTP) for full access
- A **"Continue as guest"** button at the bottom for immediate free-tools access

Clicking "Continue as guest" issues an OAuth Bearer token instantly — no Zerodha credentials
needed. Guest tokens give access to all public market data tools; personal tools return
`"not_authenticated"` for guest users.

### Option A — Via agent (recommended for full login)

Ask any connected agent:

> *"Log in to Zerodha"*

The agent calls `zerodha_login()` and returns a login URL:

```json
{
  "authenticated": false,
  "login_url": "https://zerodha-mcp-production.up.railway.app/login",
  "message": "Open login_url in your browser. Credentials are entered directly — they never pass through the agent."
}
```

Open that URL in your browser, fill in your Client ID, Kite password, and current TOTP code,
and click **Log in securely**. The server authenticates with Zerodha and saves the session.
Your API key is shown on the success page — copy it for use with non-OAuth clients (Claude Code,
Claude Desktop with Bearer header, Cursor, Postman).

### Option B — Open the login page directly

Navigate to the login page in your browser without involving an agent:

- **Local:** `http://localhost:8000/login`
- **Railway:** `https://zerodha-mcp-production.up.railway.app/login`

The same page with the Zerodha form and "Continue as guest" button is shown.

### Option C — Auto-login on server startup

If `ZERODHA_USER_ID`, `ZERODHA_PASSWORD`, and `ZERODHA_TOTP_SECRET` are all set in `.env`
(or Railway environment variables), the server logs in automatically on startup. This is the
recommended approach for Railway deployments — credentials stay in Railway's secret manager,
never in agent context.

### Check session status

```
check_auth_status()
```

Returns `authenticated: true` only for a full Zerodha login. Guest tokens return `authenticated: false`.

```json
{
  "authenticated": true,
  "backend": "ZerodhaWebClient"
}
```

Or hit the JSON status endpoint directly: `GET /auth/status`

---

## Add to your MCP client

The server exposes two transports — use whichever your client supports:

| Transport | URL | Use for |
|-----------|-----|---------|
| Streamable HTTP | `/mcp` | claude.ai, Claude Code, Cursor, Postman, modern MCP clients |
| SSE | `/sse` | Claude Desktop, legacy MCP clients |

Replace `localhost:8000` with your Railway URL for the hosted deployment.

### Security model

| Tool category | Auth required | How |
|---------------|---------------|-----|
| Market data, technicals, options, dashboards | No | Works for both guest and full-login tokens |
| Portfolio, orders, journal, recommendations | Full login only | Guest tokens return "not_authenticated"; full Bearer token required |

Your Bearer token travels in the HTTP header — it is never visible in chat or tool arguments.
The AI model never sees it.

Connecting without a token to `/mcp` or `/sse` returns `401 + WWW-Authenticate: Bearer resource_metadata=...`,
which triggers automatic OAuth discovery in supporting MCP clients.

### claude.ai (OAuth — no API key needed)

1. Open claude.ai → **Settings → Integrations → Add MCP Server**
2. Paste the MCP endpoint URL: `https://zerodha-mcp-production.up.railway.app/mcp`
3. A login popup appears automatically (OAuth 2.0 + PKCE).
4. Choose **"Continue as guest"** for immediate access to free market data tools, **or** sign in with your Zerodha credentials for full access to all 69 tools.
5. Done — the token is managed automatically. No API key to copy or paste.

### Claude Code (CLI)

```bash
# Get your API key from /login first, then:
claude mcp add --transport http zerodha https://zerodha-mcp-production.up.railway.app/mcp \
  --header "Authorization: Bearer <your-api-key>"
```

For local development:

```bash
claude mcp add --transport http zerodha http://localhost:8000/mcp \
  --header "Authorization: Bearer <your-api-key>"
```

### Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or
`%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "zerodha": {
      "url": "https://zerodha-mcp-production.up.railway.app/sse",
      "headers": { "Authorization": "Bearer <your-api-key>" }
    }
  }
}
```

Restart Claude Desktop after saving. An OAuth popup may appear on first connection.

### Cursor

Create or edit `.cursor/mcp.json` in your project root:

```json
{
  "mcpServers": {
    "zerodha": {
      "url": "https://zerodha-mcp-production.up.railway.app/mcp",
      "headers": { "Authorization": "Bearer <your-api-key>" }
    }
  }
}
```

### Postman

**New → MCP Server → Streamable HTTP** → paste the `/mcp` endpoint URL.
Free market data tools work with no auth header. For portfolio tools, add
`Authorization: Bearer <your-api-key>`.

### Any MCP-compatible agent or framework

The server follows the [MCP specification](https://modelcontextprotocol.io) — it works with any
client or agent framework that speaks MCP over HTTP. Examples:

```python
# Python MCP client
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

async with streamablehttp_client("http://localhost:8000/mcp") as (read, write, _):
    async with ClientSession(read, write) as session:
        await session.initialize()
        tools = await session.list_tools()
```

```typescript
// TypeScript / Node.js
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";

const client = new Client({ name: "my-agent", version: "1.0.0" });
const transport = new StreamableHTTPClientTransport(
  new URL("http://localhost:8000/mcp")
);
await client.connect(transport);
```

Works with: Claude Desktop, Claude Code, claude.ai web connectors, LangChain MCP adapters,
LlamaIndex MCP tool loaders, custom agent loops, or any other MCP client.

---

## MCP tools reference

### Authentication (2 tools)

| Tool | Auth needed | Description |
|------|-------------|-------------|
| `zerodha_login(user_id, password, totp_code?, totp_secret?)` | No | Log in to Zerodha. Pass either `totp_code` (6-digit) or `totp_secret` (base32). |
| `check_auth_status()` | No | Returns `{authenticated, backend}` without an API call. |

### Portfolio (4 tools)

Require an active session.

| Tool | Description |
|------|-------------|
| `get_profile()` | Your name, email, broker, and enabled exchanges |
| `get_holdings()` | Long-term demat holdings with P&L |
| `get_positions()` | Intraday and carry-forward positions |
| `get_margins(segment?)` | Available fund margins (`equity` or `commodity`) |

### Market data (7 tools)

No authentication required. Data via NSE public feed and Yahoo Finance.

| Tool | Description |
|------|-------------|
| `get_quote(instruments)` | Full quote: last price, OHLC, change, volume |
| `get_ohlc(instruments)` | Today's OHLC snapshot |
| `get_ltp(instruments)` | Last traded price only (fastest) |
| `get_historical_data(symbol, from_date, to_date, interval)` | Historical OHLCV candles (adjusted) |

Symbol format: `NSE:INFY`, `BSE:RELIANCE`, `NSE:NIFTY 50`, or raw yfinance ticker (`INFY.NS`, `^NSEI`).

### Options & derivatives (8 tools)

| Tool | Description |
|------|-------------|
| `get_expiries(symbol)` | Available expiry dates |
| `get_nifty_option_chain(expiry?)` | NIFTY chain: CE/PE OI, IV, LTP |
| `get_banknifty_option_chain(expiry?)` | BANKNIFTY chain |
| `get_equity_option_chain(symbol)` | Any NSE F&O equity chain |
| `calculate_pcr(symbol)` | Put-call ratio + sentiment |
| `get_oi_analysis(symbol)` | Top OI strikes |
| `identify_support_resistance_from_oi(symbol)` | S/R levels from OI concentration |
| `calculate_max_pain(symbol)` | Max pain strike |

### Instruments (3 tools)

| Tool | Description |
|------|-------------|
| `search_instruments(query, exchange?, limit?)` | Search by name or symbol |
| `get_instruments(exchange?)` | Full NSE equity list (~2000 rows) |
| `invalidate_instruments_cache()` | Force refresh from NSE CSV |

### Technicals (6 tools)

Daily EOD adjusted candles via Yahoo Finance.

| Tool | Description |
|------|-------------|
| `calculate_rsi(symbol, period?)` | Relative Strength Index |
| `calculate_ema(symbol, period?)` | Exponential Moving Average |
| `calculate_macd(symbol)` | MACD 12/26/9 |
| `calculate_adx(symbol)` | ADX + DI± (trend strength) |
| `calculate_atr(symbol)` | Average True Range |
| `analyze_technicals(symbol)` | All indicators in one call |

### Analysis (6 tools)

⚠️ See [Research findings](#research-findings) before using these tools.

| Tool | Description |
|------|-------------|
| `detect_market_regime(symbol)` | Market structure descriptor: observed boolean facts (price_above_ema20, ema20_above_ema50, adx_above_25, rsi_above_60) + auto-generated descriptor array. **Not a directional signal.** |
| `generate_trade_setup(symbol)` | Entry/stoploss/target reference levels + market_structure + observation-only reasoning. **No demonstrated edge.** |
| `get_regime_alignment(symbol)` | Daily/weekly/monthly regime agreement (STRONG/PARTIAL/CONFLICT/MIXED) |
| `recommend_strategy(symbol)` | Maps market structure to options strategy type |
| `calculate_risk_reward(entry, stoploss, target)` | Absolute risk, reward, and RR ratio |
| `calculate_position_size(capital, risk_percent, entry, stoploss)` | Quantity from capital and risk % |

### Dashboard (2 tools)

| Tool | Description |
|------|-------------|
| `get_nifty_dashboard()` | Full NIFTY snapshot: technicals, regime, OI, VIX, risk score |
| `get_banknifty_dashboard()` | Full BANKNIFTY snapshot |

### Trade planner (1 tool)

| Tool | Description |
|------|-------------|
| `create_trade_plan(symbol, direction, capital)` | Entry/sizing/quality plan from analysis; includes calibration adjustment if journal has enough trades |

### Option strategy builder (1 tool)

| Tool | Description |
|------|-------------|
| `build_option_strategy(symbol, strategy_type, expiry?, strikes?)` | Builds specific options structures with strikes, premiums, max profit/loss, breakevens |

### Trade review (1 tool)

| Tool | Description |
|------|-------------|
| `review_trade(trade_id)` | HOLD/REDUCE/EXIT verdict with thesis evaluation, P&L, and stop analysis |

### Market intelligence (4 tools)

| Tool | Description |
|------|-------------|
| `get_india_vix()` | India VIX with regime classification (LOW/ELEVATED/HIGH/EXTREME) |
| `get_global_pulse()` | US futures, Dollar Index, crude, gold — global risk sentiment |
| `get_upcoming_events()` | RBI MPC, FOMC, CPI, NFP, GDP — upcoming macro events with impact ratings |
| `get_market_risk_score()` | Composite risk score (0–100) from VIX, PCR, global pulse, events |

### Portfolio intelligence (3 tools)

| Tool | Description |
|------|-------------|
| `get_portfolio_risk_report()` | Per-position risk scores, value-weighted portfolio score, HHI diversification |
| `get_portfolio_regime_analysis()` | Regime distribution across holdings |
| `get_portfolio_exposure_breakdown()` | Exposure by sector and instrument type |

### Catalyst intelligence (4 tools)

| Tool | Description |
|------|-------------|
| `get_symbol_news(symbol)` | Recent news headlines with keyword-based sentiment |
| `get_news_sentiment(symbol)` | Aggregated sentiment score |
| `get_earnings_calendar(symbol)` | Next earnings date, proximity scoring, corporate actions |
| `get_event_risk(symbol)` | Composite event risk: earnings 40% + news 30% + market risk 30% |

### Trade journal (7 tools)

| Tool | Description |
|------|-------------|
| `log_trade(symbol, direction, entry, quantity, ...)` | Open a trade record |
| `close_trade(trade_id, exit_price)` | Close a trade, calculate P&L |
| `get_open_trades()` | All open positions in the journal |
| `get_trade_history(status?, symbol?)` | Closed trade history |
| `get_performance_analytics()` | P&L by signal, regime, and confidence band |
| `get_orders()` | Today's Zerodha orders (requires session) |
| `sync_trades_from_zerodha()` | Auto-import completed Zerodha orders into journal |

### Calibration (1 tool)

| Tool | Description |
|------|-------------|
| `get_calibration_report()` | Brier score, reliability curve, overconfidence analysis from journal history |

### Trade recommendations (3 tools)

| Tool | Description |
|------|-------------|
| `recommend_trade(symbol, direction?, capital?)` | Portfolio-aware ENTER/WAIT/AVOID — gates on event risk, VIX, duplicate exposure |
| `review_open_trades()` | HOLD/REDUCE/EXIT verdict for all open journal trades |
| `get_daily_brief()` | Morning briefing: market context, VIX, upcoming events, open trade alerts |

### Position sizing (3 tools)

| Tool | Description |
|------|-------------|
| `size_equity_trade(symbol, direction, capital, risk_percent)` | Lot size from risk budget and stoploss distance |
| `size_options_trade(symbol, strategy, capital, risk_percent)` | Options lots from premium distance and lot size |
| `size_from_recommendation(symbol, capital)` | Full pipeline: recommend_trade → size → portfolio heat adjustment |

### Decision quality / Phase 22 (5 tools)

| Tool | Description |
|------|-------------|
| `log_recommendation(symbol, user_question, market_snapshot, mcp_facts, claude_reasoning_summary, recommendation_type, uncertainty_level)` | Log a Claude recommendation for later blind postmortem review |
| `update_recommendation_outcome(id, user_action?, mcp_changed_decision?, decision_quality?, outcome_1d?, ...)` | Fill postmortem during weekly review |
| `get_recommendation_stats()` | Partition counts (bootstrap / clean / baseline) and analysis readiness |
| `get_full_market_context(symbol, include_options?)` | Single call replacing 6 separate calls: quote + OHLC + technicals + market_structure + VIX + events |
| `detect_recommendation(text)` | Scan text for ENTER/EXIT/HOLD/AVOID trigger phrases (does not auto-log) |

---

## Tool response format

Every tool response is wrapped in a trust metadata envelope:

```json
{
  "data": { "...actual output..." },
  "meta": {
    "type": "FACT | INDICATOR | INTERPRETATION",
    "validation": {
      "status": "VERIFIED | MATHEMATICALLY_COMPUTED | UNVALIDATED",
      "backtested": false,
      "research_status": "EXPERIMENTAL | INVALIDATED | NOT_TESTED"
    },
    "data_quality": "VALID | NaN_DETECTED | STALE | INVALID",
    "market_hours": true,
    "source": "yfinance | NSELive | internal_journal",
    "deprecated_fields_present": [],
    "schema_version": 5,
    "as_of": "2026-06-20T08:00:00Z"
  }
}
```

`detect_market_regime` and `generate_trade_setup` return structural descriptors, not signals:

```json
{
  "data": {
    "market_structure": {
      "price_above_ema20": true,
      "ema20_above_ema50": true,
      "adx_above_25": true,
      "rsi_above_60": true,
      "descriptor": ["price_above_ema20", "ema20_above_ema50", "adx_above_25", "rsi_above_60"],
      "indicator_interpretation": {
        "type": "INTERPRETATION",
        "validation_status": "UNVALIDATED",
        "adx_note": "trend_present",
        "rsi_note": "momentum_elevated"
      }
    }
  }
}
```

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
| `TURSO_DATABASE_URL` | No | — | Turso cloud SQLite URL (uses local `journal.db` if unset) |
| `TURSO_AUTH_TOKEN` | No | — | Turso auth token (required if `TURSO_DATABASE_URL` is set) |

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

## Research findings

Two research phases found **no demonstrated directional edge** in the analysis tools:

**Phase 20A — Regime classifier walk-forward audit (2022–2025, Nifty 50)**
BULL_TREND average 10-day return: −0.354% aggregate, −0.608% at run-start.
Monotonicity violated. The EMA20/EMA50 + ADX regime engine does not demonstrate directional
predictive value on NSE equities.

**Phase 21 — Cross-sectional momentum screen (Nifty 50, 968 dates, 46,464 obs)**
RS_6m Q5−Q1 spread: −0.286% per 10 days. RS_12m1: −0.141%. Both non-monotone.
No large, stable, tradeable cross-sectional momentum edge.

**What this means for the tools:**
- `detect_market_regime` → returns structural facts (`price_above_ema20`, etc.), not predictions
- `generate_trade_setup` → returns reference levels (entry/stoploss/target) and observation-only reasoning, not signals
- `recommend_strategy` → maps structure to options strategy type; not a trade recommendation
- Confidence and signal fields have been removed entirely from analysis tool outputs

The research audit framework and cross-sectional screen scripts are retained in `scripts/` for
evaluating future models.

---

## Limitations

| Feature | Status | Alternative |
|---------|--------|-------------|
| Order placement | Not available | Zerodha blocks programmatic orders via web sessions. Use the Kite app. |
| F&O / MCX instrument dump | Not available | NSE equity list only. Search by symbol works for most lookups. |
| Real-time WebSocket ticker | Not available | Poll `get_ltp()` every few seconds for price updates. |
| Intraday history older than 60 days | Not available | Use `interval="1d"` for full daily history going back years. |
| BSE instrument list | Not available | Use `search_instruments(query, exchange="BSE")` or yfinance tickers directly. |
| Directional trade signals | Intentionally removed | Phase 20A and 21 found no edge. Use structural descriptors for context only. |

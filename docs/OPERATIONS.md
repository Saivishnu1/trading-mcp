# Operations

## Access tiers

| Tier | Who | How | Tools available |
|---|---|---|---|
| **Guest** | Anyone | Click "Continue as guest" on the OAuth login page | 50+ free tools: market data, options, technicals, dashboards, analysis |
| **Full login** | Account owner | Enter Zerodha credentials on the OAuth login page | All tools, including portfolio, journal, recommendations, order execution |

Market data tools work immediately, no login required. Portfolio tools (`get_holdings`,
`get_positions`, `get_margins`), the journal, order execution, and recommendations require a
full Zerodha login.

> **Security design:** credentials never pass through the agent. The `zerodha_login()` MCP tool
> takes no parameters — it returns a URL. You open the URL in your browser and enter credentials
> directly into the server's login page. Nothing sensitive appears in agent context, tool logs,
> or MCP traffic.

### How the login page works

When an MCP client connects to `/mcp` or `/sse` without a token, the server returns `401` with
`WWW-Authenticate: Bearer resource_metadata=...`. MCP clients that support OAuth (claude.ai,
Claude Desktop) open a login popup automatically. The `/oauth/authorize` page shows a Zerodha
login form (Client ID + password + TOTP) and a "Continue as guest" button.

### Logging in via an agent

Ask any connected agent to *"Log in to Zerodha"*. It calls `zerodha_login()`, which returns a
login URL. Open it, fill in Client ID / password / TOTP, and the server authenticates and saves
the session. Your API key is shown on the success page for non-OAuth clients.

### Auto-login on server startup

If `ZERODHA_USER_ID`, `ZERODHA_PASSWORD`, and `ZERODHA_TOTP_SECRET` are all set, the server logs
in automatically on startup — credentials stay in the environment/secret manager, never in agent
context. This is the recommended setup for a persistent deployment.

### Checking session status

```
check_auth_status()
```
returns `{"authenticated": true, "backend": "ZerodhaWebClient"}` for a full login, or
`authenticated: false` for a guest token. Or hit `GET /auth/status` directly.

---

## Session lifetime and daily re-login

Zerodha's `enctoken` (session token) **expires every day at approximately 07:30 IST** when
Zerodha resets all active sessions for end-of-day processing.

- The server saves the token to `.session.json` (or `SESSION_FILE`) and reloads it on restart.
- After 07:30 IST, portfolio/order tools return `401 Unauthorized` until you log in again.
- Market data tools (`get_quote`, `get_ltp`, `get_historical_data`) are **not affected** — they
  never need a Zerodha session.

If `ZERODHA_TOTP_SECRET` is set, automate re-login with a daily restart after the reset:

```bash
# crontab -e — restart at 07:45 IST (02:15 UTC) every day
15 2 * * * docker compose -f /path/to/trading-mcp/docker-compose.yml restart
```

On startup the server auto-calls `zerodha_login()` using the credentials in the environment if
a valid `ZERODHA_TOTP_SECRET` is present — no manual intervention needed. (The production
deployment instead runs this as a systemd service; see [`../infra/README.md`](../infra/README.md).)
Alternatively, just ask Claude to log you back in each morning — it's one message.

---

## Switching broker backends

The server has two broker implementations behind an abstract interface; switching does not
change any MCP tool's behavior.

| Backend | When to use |
|---|---|
| `zerodha_web` (default) | Direct `httpx` calls to `kite.zerodha.com`. Fastest, no extra deps. |
| `jugaad` | If Zerodha changes their internal web API and the primary client breaks. Uses `jugaad-trader`. |

```env
# .env
BROKER_BACKEND=jugaad
```

Restart the server. Switch back by setting `BROKER_BACKEND=zerodha_web` or removing the variable.

---

## Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `ZERODHA_USER_ID` | **Yes** | — | Your Zerodha client ID (e.g. `ZK1234`) |
| `ZERODHA_PASSWORD` | **Yes** | — | Your Kite login password |
| `ZERODHA_TOTP_SECRET` | No | — | Base32 TOTP secret for automatic code generation |
| `BROKER_BACKEND` | No | `zerodha_web` | `zerodha_web` (primary) or `jugaad` (fallback) |
| `SESSION_FILE` | No | `.session.json` | Where the enctoken is persisted between restarts |
| `HOST` | No | `0.0.0.0` | Server bind address |
| `PORT` | No | `8000` | Server port |
| `LOG_LEVEL` | No | `INFO` | `DEBUG`, `INFO`, `WARNING`, or `ERROR` |
| `DATABASE_URL` | Prod only | — | PostgreSQL URL (Oracle VM); SQLite/Turso used otherwise |
| `TURSO_DATABASE_URL` | No | — | Turso cloud SQLite URL (uses local `journal.db` if unset) |
| `TURSO_AUTH_TOKEN` | No | — | Turso auth token (required if `TURSO_DATABASE_URL` is set) |

See [`.env.example`](../.env.example) for the full list including monitor/Telegram settings.

---

## Local development with Docker

```bash
docker compose up -d          # start
docker compose logs -f        # follow logs
docker compose down           # stop
```

## Running without Docker

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh   # install uv if needed
uv sync
uv run zerodha-mcp
```

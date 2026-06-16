# Migration Guide — Kite Connect → Zerodha Personal APIs

## What changed and why

The original server used **Kite Connect** (Zerodha's paid developer API, ~₹2000/month).
This migration replaces it with:

| Layer | Before | After |
|-------|--------|-------|
| Auth | OAuth redirect + API key/secret | Web login (user_id, password, TOTP) |
| Portfolio data | `kiteconnect.KiteConnect` | `ZerodhaWebClient` (direct httpx) |
| Live quotes | Kite Connect websocket/REST | `jugaad-data` NSELive (NSE) / yfinance |
| Historical data | Kite historical API | Yahoo Finance (`yfinance`) |
| Instruments | Kite instrument dump (~4 MB) | NSE public EQUITY_L.csv |
| Fallback broker | — | `jugaad-trader` (set `BROKER_BACKEND=jugaad`) |

---

## 1 — Files modified

| File | Change |
|------|--------|
| `pyproject.toml` | Removed `kiteconnect`; added `httpx`, `jugaad-trader`, `jugaad-data`, `yfinance`, `pyotp` |
| `src/kite_client.py` | **Deprecated** — now raises `ImportError`. Dead code; safe to delete. |
| `src/tools/auth.py` | Replaced OAuth flow with `zerodha_login()` + new `check_auth_status()` |
| `src/tools/portfolio.py` | Now calls `get_broker()` from `src/broker/` instead of `get_kite()` |
| `src/tools/market.py` | All tools now use `get_market()` from `src/market/`; see breaking changes |
| `src/tools/instruments.py` | Now uses NSE public CSV instead of Kite instrument endpoint |
| `src/server.py` | Updated instructions; loads `src/broker/` factory on startup |
| `.env.example` | Removed `ZERODHA_API_KEY/SECRET`; added `ZERODHA_USER_ID/PASSWORD/TOTP_SECRET` |

## 2 — Files added

```
src/broker/
  base.py          BrokerClient Protocol (structural interface)
  zerodha_web.py   Primary: direct httpx to kite.zerodha.com
  jugaad.py        Fallback: jugaad-trader wrapper
  __init__.py      Factory (reads BROKER_BACKEND env var)

src/market/
  base.py          MarketClient Protocol
  service.py       Unified: NSELive → yfinance resolution
  __init__.py      MarketService singleton
```

---

## 3 — Environment variables

### Remove
```
ZERODHA_API_KEY
ZERODHA_API_SECRET
ZERODHA_ACCESS_TOKEN
TOKEN_FILE
```

### Add
```
ZERODHA_USER_ID       # your Zerodha client ID
ZERODHA_PASSWORD      # your trading password
ZERODHA_TOTP_SECRET   # base32 TOTP secret (optional — enables auto-login)
BROKER_BACKEND        # zerodha_web (default) | jugaad
SESSION_FILE          # path to persist enctoken (default .session.json)
LOG_LEVEL             # INFO (default) | DEBUG | WARNING
```

---

## 4 — Breaking API changes in MCP tools

### `zerodha_login` replaces `get_login_url` + `generate_session`

**Before (Kite Connect)**
```
get_login_url()                  → user opens browser URL
generate_session(request_token)  → exchanges token
```

**After (Personal API)**
```
zerodha_login(
  user_id="ZK1234",
  password="mypassword",
  totp_code="123456"           # one of these two
  totp_secret="BASE32SECRET"   # ─────────────────
)
```

`get_login_url()` and `generate_session()` are **removed**.
`check_auth_status()` is new.

---

### `get_historical_data` — signature change

**Before**
```
get_historical_data(
  instrument_token=408065,   # numeric Kite token
  from_date="2024-01-01",
  to_date="2024-12-31",
  interval="day",            # Kite interval string
  continuous=False,
  oi=False,
)
```

**After**
```
get_historical_data(
  symbol="NSE:INFY",         # human-readable symbol
  from_date="2024-01-01",
  to_date="2024-12-31",
  interval="1d",             # yfinance interval (Kite aliases also work)
)
```

Kite-style intervals are auto-translated (`"day"→"1d"`, `"minute"→"1m"`, etc.).
`continuous` and `oi` parameters are removed (not available in yfinance).

---

### `get_instruments` — NSE only via free CSV

**Before**: Full dump from Kite for NSE, BSE, NFO, CDS, BFO, MCX, BCD.

**After**: NSE equity only from public CSV. `exchange="BSE"` raises `ValueError`.
Use `search_instruments(query, exchange=None)` across exchanges.

---

## 5 — Features that cannot work with Personal APIs

| Feature | Kite Connect | Personal API alternative |
|---------|-------------|--------------------------|
| Order placement | `place_order()` | **Not available** — Zerodha blocks programmatic orders from web sessions. Use Kite app manually, or subscribe to Kite Connect for this feature only. |
| F&O instrument dump (NFO/MCX) | Full Kite instruments endpoint | NSE FO bhavcopy CSV (not yet implemented — open a PR) |
| Open interest data in historical | `oi=True` parameter | Not available in yfinance |
| Intraday data beyond 60 days | Any Kite interval | Yahoo Finance limit — use daily candles for older data |
| WebSocket live ticker | `KiteTicker` | Not available — poll `get_ltp()` or `get_quote()` instead |

---

## 6 — Switching the broker backend

If Zerodha changes their web API and `ZerodhaWebClient` breaks, switch to jugaad-trader
without touching any MCP tool code:

```env
# .env
BROKER_BACKEND=jugaad
```

Restart the server. All portfolio tools continue to work identically.
To switch back: `BROKER_BACKEND=zerodha_web` (or remove the variable).

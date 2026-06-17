# Zerodha Personal MCP — Development Log

**Repository:** `trading-mcp`
**Deployed:** Railway (`zerodha-mcp-production.up.railway.app`)
**Date:** 2026-06-17

---

## Project Overview

A personal Model Context Protocol (MCP) server that connects Claude to a Zerodha
trading account **without** requiring a paid Kite Connect subscription. Built in four
phases across a single day, going from a bare authentication stub to a 33-tool
trading intelligence platform.

---

## Architecture

```
src/
├── broker/          Zerodha session management (zerodha_web + jugaad fallback)
├── market/          yfinance-backed OHLCV and quote service
├── options/         NSE option chain fetch (jugaad-data NSELive) + analytics
├── technical/       Pure-Python indicator math (RSI, EMA, MACD, ADX, ATR)
├── analysis/        Market regime detection, trade setup, strategy recommendation
├── dashboard/       Aggregator — assembles all intelligence into one snapshot
├── tools/           MCP tool registrations (one file per domain)
└── server.py        FastMCP server + ASGI app + /health endpoint
```

**Transport:** Streamable HTTP at `/mcp` (for claude.ai web connectors) + SSE at `/sse`
**Auth:** Session file persisted to disk; survives server restarts (~24h lifetime)
**Deployment:** Railway auto-deploys on push to `main`

---

## Phase 0 — Base Server

**Commit:** `50440b9` — `feat: Zerodha personal-account MCP server`
**Tools at end of phase:** 13

### What was built

- Full Zerodha session management via direct `httpx` calls to `kite.zerodha.com`
  (no paid Kite Connect API subscription required)
- `jugaad-trader` as an optional fallback broker backend
- TOTP auto-generation from `totp_secret` (no manual code entry needed)
- Session persistence to disk — survives server restarts
- Streamable HTTP transport (`/mcp`) for claude.ai web connector compatibility
- SSE transport (`/sse`) for legacy MCP clients
- `/health` endpoint for Railway health checks
- ASGI routing: lifespan events → http_app; `/sse` → sse_app; `/mcp` → http_app

### Fixes applied during phase

| Commit | Fix |
|---|---|
| `506af45` | Fix `/mcp` 404 — use raw ASGI dispatch instead of Starlette Mount |
| `15d90c9` | Fix task group init — route lifespan to http_app, SSE to sse_app |
| `e8765a6` | Allow Railway hostname in TransportSecuritySettings (was causing 421) |
| `644c59c` | Fix `get_quote` — fall back to `ticker.history()` when `fast_info` fails |

### Tools (13)

| Tool | Auth | Description |
|---|---|---|
| `zerodha_login` | — | Log in with user_id, password, TOTP |
| `check_auth_status` | — | Check if an active session exists |
| `get_profile` | ✓ | User profile (name, email, exchanges) |
| `get_holdings` | ✓ | Demat holdings with P&L |
| `get_positions` | ✓ | Intraday and carry-forward positions |
| `get_margins` | ✓ | Available fund margins |
| `get_quote` | — | Full market quote |
| `get_ohlc` | — | Today's OHLC + LTP |
| `get_ltp` | — | Last traded price only |
| `get_historical_data` | — | Historical OHLCV candles (yfinance) |
| `get_instruments` | — | Full instrument list for an exchange |
| `search_instruments` | — | Search by symbol or company name |
| `invalidate_instruments_cache` | — | Refresh in-memory instrument cache |

---

## Phase 1 — Options

**Commits:** `95329ac`, `f4f6d1f`, `0a088cc`
**Tag:** *(none — tagged retroactively as part of phase-3)*
**Tools added:** 7 → **Total: 20**

### Files created

| File | Purpose |
|---|---|
| `src/options/__init__.py` | Package init |
| `src/options/service.py` | NSE option chain fetcher with 60s cache |
| `src/options/analytics.py` | Pure analytics functions (no I/O) |
| `src/tools/options.py` | 7 MCP tool registrations |

### Design decisions

**Data source problem:** The NSE public API endpoint `/api/option-chain-indices`
was deprecated (404). The replacement `/api/option-chain-v3` was soft-blocked for
datacenter IPs (returns empty `{}`). Solved by using `jugaad-data`'s `NSELive`
library (already a project dependency used by the market service), with the v3
httpx path as a fallback.

**Schema normalisation:** `jugaad-data` returns row-level expiry as `expiryDates`
(plural); the direct NSE API uses `expiryDate` (singular). The service normalises
all rows to `expiryDate` so analytics functions need no source awareness.

**Cache:** 60-second TTL per `(symbol, expiry)` key. Thread-safe with `threading.Lock`.

### Analytics implemented (pure Python, no I/O)

- **PCR** — Put-Call Ratio by OI and by volume, with sentiment interpretation
- **Max pain** — Wilder's method: strike where total ITM option value is minimised
- **OI analysis** — Top-N call and put strikes by open interest
- **Support/Resistance** — Highest put OI = support, highest call OI = resistance;
  nearest levels above and below spot returned separately

### Tools (7)

| Tool | Description |
|---|---|
| `get_expiries` | Available expiry date strings for NIFTY/BANKNIFTY/FINNIFTY/MIDCPNIFTY |
| `get_nifty_option_chain` | NIFTY CE/PE OI, volume, IV, LTP per strike (ATM±N filter) |
| `get_banknifty_option_chain` | Same for BANKNIFTY |
| `calculate_pcr` | PCR (OI + volume) with bullish/bearish interpretation |
| `get_oi_analysis` | Top-N OI strikes for calls and puts |
| `identify_support_resistance_from_oi` | Support and resistance zones from OI |
| `calculate_max_pain` | Max pain strike + pain table top 20 |

### Runtime issue found and fixed

During verification, the original hardcoded endpoint (`/api/option-chain-indices`)
returned 404. Endpoint was migrated to v3 with browser-like cookie priming, and
`jugaad-data` NSELive was promoted to primary source.

---

## Phase 2 — Technicals

**Commit:** `0a088cc` (bundled with Phase 1 fixes)
**Tools added:** 6 → **Total: 26**

### Files created

| File | Purpose |
|---|---|
| `src/technical/__init__.py` | Package init |
| `src/technical/indicators.py` | Pure-Python indicator math |
| `src/tools/technicals.py` | 6 MCP tool registrations + `_load_closes` helper |

### Design decisions

**No TA-Lib, no numpy** — all math implemented in pure Python to avoid binary
dependencies and keep the Docker image lightweight.

**OHLCV source** — reuses the existing `get_market().get_historical()` path
(yfinance-backed). A `_resolve()` helper maps friendly index names to yfinance
tickers (`NIFTY` → `^NSEI`, `BANKNIFTY` → `^NSEBANK`, etc.).

**Wilder's smoothing** used for RSI, ADX, ATR (matches TradingView / most charting
platforms). Standard exponential smoothing used for EMA and MACD.

### Indicators implemented

| Indicator | Algorithm | Notes |
|---|---|---|
| RSI | Wilder's smoothing | Returns `None` if insufficient data |
| EMA | Standard EMA seeded with SMA | Parameterised period |
| MACD | EMA(12) − EMA(26), signal EMA(9) | Returns macd/signal/histogram |
| ADX | Wilder's DM smoothing | Returns adx/+DI/-DI |
| ATR | Wilder's TR smoothing | Average True Range |

### Tools (6)

| Tool | Description |
|---|---|
| `calculate_rsi` | RSI(N) for any symbol, default period=14 |
| `calculate_ema` | EMA(N), default period=20 |
| `calculate_macd` | MACD 12/26/9 — macd line, signal, histogram |
| `calculate_adx` | ADX(14) with +DI/-DI |
| `calculate_atr` | ATR(14) |
| `analyze_technicals` | All indicators in one call |

### Symbol resolution

`NIFTY`, `BANKNIFTY`, `SENSEX`, `FINNIFTY`, `MIDCPNIFTY` → yfinance index tickers.
`NSE:INFY`, `BSE:RELIANCE` → passed to market service (`INFY.NS`, `RELIANCE.NS`).
Anything else passed through unchanged (raw yfinance ticker).

---

## Phase 3 — Analysis

**Commits:** `0a088cc` (initial), `a3907e3` (schema reconciliation)
**Tag:** `phase-3-analysis-complete`
**Tools added:** 5 → **Total: 31**

### Files created

| File | Purpose |
|---|---|
| `src/analysis/__init__.py` | Package init |
| `src/analysis/regime.py` | Regime detection, trade setup, strategy, risk tools |
| `src/tools/analysis.py` | 5 MCP tool registrations |

### Design decisions

**Reuse `_load_closes`** from `src/tools/technicals.py` — `_analyze_technicals()`
in `regime.py` calls it directly instead of duplicating the yfinance fetch logic.

**Regime classification** — deterministic rules on EMA20/EMA50 crossover + ADX
threshold + RSI + price position:

| Regime | Conditions |
|---|---|
| `BULL_TREND` | EMA20 > EMA50 AND ADX > 25 |
| `BEAR_TREND` | EMA20 < EMA50 AND ADX > 25 |
| `BREAKOUT_POTENTIAL` | 20 ≤ ADX ≤ 25 AND RSI > 55 AND price > EMA20 |
| `RANGE_BOUND` | ADX < 20 |
| `NEUTRAL_BULLISH` | Price > EMA20 AND RSI > 55 (default bullish) |
| `NEUTRAL_BEARISH` | Price < EMA20 AND RSI < 45 (default bearish) |

**Scoring system for trade setup** — independent bullish/bearish counters (not
a single net score) so `NEUTRAL_BULLISH` and `NEUTRAL_BEARISH` can be output
even when the scores are close but not tied.

**Strategy mapping:**

| Regime | RSI condition | Strategy |
|---|---|---|
| BULL_TREND | RSI ≥ 60 | Long Call |
| BULL_TREND | RSI < 60 | Bull Call Spread |
| NEUTRAL_BULLISH | — | Bull Call Spread |
| RANGE_BOUND | — | Iron Condor |
| NEUTRAL_BEARISH | — | Bear Put Spread |
| BEAR_TREND | RSI ≤ 40 | Long Put |
| BEAR_TREND | RSI > 40 | Bear Put Spread |
| BREAKOUT_POTENTIAL | ADX ≥ 23 | Long Straddle |
| BREAKOUT_POTENTIAL | ADX < 23 | Long Strangle |

### Schema reconciliation (commit `a3907e3`)

The initial Phase 3 implementation of `generate_trade_setup` **removed** the
legacy scalar fields (`entry`, `stoploss`, `target`) and replaced them with a
zone schema (`entry_above`, `entry_below`, `bull_target`, `bear_target`).

This was a breaking change for any future Dashboard, Journal, Alerts, or Trade
Planner consumer. Both schemas were reconciled into a single response:

```json
{
  "signal": "BUY",
  "confidence": 70,
  "entry":    24157.04,
  "stoploss": 23657.62,
  "target":   24513.77,
  "entry_above": 24157.04,
  "entry_below": 24014.35,
  "bull_target": 24513.77,
  "bear_target": 23657.62,
  "reasoning": [...]
}
```

Legacy fields are derived from zone fields (not re-calculated), so both schemas
are always in sync regardless of signal value.

### Tools (5)

| Tool | Description |
|---|---|
| `detect_market_regime` | BULL_TREND / BEAR_TREND / RANGE_BOUND / BREAKOUT_POTENTIAL / NEUTRAL_BULLISH / NEUTRAL_BEARISH |
| `generate_trade_setup` | BUY / SELL / NEUTRAL / NEUTRAL_BULLISH / NEUTRAL_BEARISH with entry/stoploss/target + zone fields |
| `recommend_strategy` | Options strategy (Long Call, Bull Spread, Iron Condor, etc.) |
| `calculate_risk_reward` | Risk/reward ratio from entry/stoploss/target |
| `calculate_position_size` | Position size from capital + risk% + stop distance |

---

## Phase 4 — Dashboard

**Commit:** `6c30ce6`
**Tag:** `phase-4-dashboard-complete`
**Tools added:** 2 → **Total: 33**

### Files created

| File | Purpose |
|---|---|
| `src/dashboard/__init__.py` | Package init |
| `src/dashboard/service.py` | Aggregator service |
| `src/tools/dashboard.py` | 2 MCP tool registrations |

### Design decisions

**No duplicated calculations** — the service delegates to existing module
functions rather than reimplementing anything:

```
_options_section()   → OptionsService.get_option_chain() (1 fetch, 60s cached)
                        analytics.calculate_pcr / max_pain / identify_sr
_technicals_section() → _load_closes() (1 yfinance fetch)
                         indicators.rsi / ema / macd / adx / atr
_analysis_section()  → detect_market_regime / generate_trade_setup / recommend_strategy
```

**Error isolation** — a failure in the options section (e.g. NSE unreachable)
does not prevent technicals or analysis from being returned. Each section catches
its own exceptions and returns `{"error": "..."}` in that section only.

**Dual spot price** — `spot_price` is taken from the option chain's
`underlyingValue` first (live NSE price), falling back to the last yfinance close.

**Deterministic summary** — built from 5 inputs: price vs EMAs, PCR level,
RSI momentum bucket, ADX trend-strength bucket, and signal value. No LLM
involvement — the same inputs always produce the same string.

### Output schema

```json
{
  "symbol": "NIFTY",
  "spot_price": 24085.70,
  "options": {
    "expiry": "23-Jun-2026",
    "pcr": 1.07,
    "pcr_interpretation": "mildly bullish",
    "max_pain": 24000.0,
    "distance_from_spot": 85.7,
    "supports": [24000, 23000, 23500, 23300, 23900],
    "resistances": [25000, 24000, 24500, 24100, 25500],
    "nearest_support": 24000,
    "nearest_resistance": 24100
  },
  "technicals": {
    "rsi": 60.87,
    "ema20": 23632.16,
    "ema50": 23839.14,
    "macd": {"macd": -6.62, "signal": -92.91, "histogram": 86.29},
    "adx": 19.77,
    "plus_di": 29.55,
    "minus_di": 23.76,
    "atr": 285.38
  },
  "analysis": {
    "regime": "RANGE_BOUND",
    "confidence": 65,
    "signal": "BUY"
  },
  "trade_setup": {
    "signal": "BUY",
    "confidence": 70,
    "entry": 24157.04,
    "stoploss": 23657.63,
    "target": 24513.77,
    "entry_above": 24157.04,
    "entry_below": 24014.35,
    "bull_target": 24513.77,
    "bear_target": 23657.63,
    "reasoning": ["RSI at 60.87 is above 55, favoring bullish momentum.", "..."]
  },
  "strategy": {
    "recommended": "Iron Condor",
    "reason": "ADX at 19.77 points to low trend strength..."
  },
  "summary": "NIFTY is trading above both key moving averages, with mildly bullish options positioning. Momentum is positive and trend strength is low. Overall bias is bullish."
}
```

### Tools (2)

| Tool | Description |
|---|---|
| `get_nifty_dashboard` | Full NIFTY snapshot — options + technicals + regime + setup + strategy + summary |
| `get_banknifty_dashboard` | Same for BANKNIFTY |

---

## Complete Tool Registry (33 tools)

### Authentication (2)
`zerodha_login`, `check_auth_status`

### Account & Portfolio (4) — require active session
`get_profile`, `get_holdings`, `get_positions`, `get_margins`

### Market Data (7) — no auth
`get_quote`, `get_ohlc`, `get_ltp`, `get_historical_data`,
`get_instruments`, `search_instruments`, `invalidate_instruments_cache`

### Options & Derivatives (7) — no auth
`get_expiries`, `get_nifty_option_chain`, `get_banknifty_option_chain`,
`calculate_pcr`, `get_oi_analysis`, `identify_support_resistance_from_oi`,
`calculate_max_pain`

### Technicals (6) — no auth
`calculate_rsi`, `calculate_ema`, `calculate_macd`,
`calculate_adx`, `calculate_atr`, `analyze_technicals`

### Analysis (5) — no auth
`detect_market_regime`, `generate_trade_setup`, `recommend_strategy`,
`calculate_risk_reward`, `calculate_position_size`

### Dashboard (2) — no auth
`get_nifty_dashboard`, `get_banknifty_dashboard`

---

## Git Tags

| Tag | Commit | Description |
|---|---|---|
| `phase-3-analysis-complete` | `a3907e3` | Analysis + schema reconciliation complete |
| `phase-4-dashboard-complete` | `6c30ce6` | Dashboard complete — final Phase 4 state |

---

## Key Technical Constraints

| Constraint | Resolution |
|---|---|
| No paid Kite Connect subscription | Direct `httpx` to `kite.zerodha.com` via `zerodha_web` broker |
| NSE API soft-blocks datacenter IPs | `jugaad-data` NSELive as primary; v3 httpx as fallback |
| No TA-Lib binary dependency | Pure-Python Wilder's smoothing for all indicators |
| No numpy requirement | All math uses Python built-ins and `round()` |
| Backward compatibility | Legacy scalar fields (`entry`/`stoploss`/`target`) always present alongside zone fields |
| Error isolation in dashboard | Each section catches independently; partial responses returned |

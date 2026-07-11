# Zerodha Personal MCP — Development Log

**Repository:** `trading-mcp`
**Deployed:** Railway (`zerodha-mcp-production.up.railway.app`)
**Date:** 2026-06-18

---

## Project Overview

A personal Model Context Protocol (MCP) server that connects Claude to a Zerodha
trading account **without** requiring a paid Kite Connect subscription. Built across
thirteen phases, from a bare authentication stub to a 55-tool trading intelligence platform
with market regime analysis, risk scoring, macro context awareness, portfolio intelligence,
company-level catalyst tracking (news, earnings, event risk), a persistent trade journal,
and a portfolio-aware trade recommendation engine.

---

## Architecture

```
src/
├── broker/                  Zerodha session management (zerodha_web + jugaad fallback)
├── market/                  yfinance-backed OHLCV and quote service
├── options/                 NSE option chain fetch (jugaad-data NSELive) + analytics
├── technical/               Pure-Python indicator math (RSI, EMA, MACD, ADX, ATR)
├── analysis/                Market regime detection, trade setup, strategy recommendation
├── planner/                 Trade plan composition — entry/sizing/quality from analysis
├── strategy/                Option strategy builder — strikes, premiums, payoffs
├── review/                  Trade reviewer — HOLD/REDUCE/EXIT thesis evaluation
├── dashboard/               Aggregator — assembles all sections into one snapshot
├── intelligence/            Market Intelligence Engine — VIX, global pulse, events, risk score
├── portfolio_intelligence/  Portfolio-level risk, regime distribution, exposure breakdown
├── catalyst/                Catalyst Intelligence — news, earnings, event risk (Phase 11B)
│   ├── constants.py         _to_yf_ticker(), keyword sets, CATALYST_PRIORITY
│   ├── news.py              get_symbol_news(), _aggregate_sentiment()
│   ├── earnings.py          get_earnings_calendar(), proximity scoring, corporate actions
│   └── event_risk.py        get_event_risk(), confidence model, dual catalyst fields
├── journal/                 Trade Journal — Turso cloud SQLite (Phase 12 + 15B)
│   ├── db.py                Connection factory (Turso/sqlite3 branch), schema init, reset_connection() test seam
│   └── service.py           log_trade, close_trade, get_open_trades, get_trade_history
├── recommendations/         Trade Recommendation Engine (Phase 13)
│   └── engine.py            recommend_trade, review_open_trades, get_daily_brief
├── tools/                   MCP tool registrations (one file per domain)
├── ui/                      Static HTML templates (served by server.py ASGI routes)
│   └── login.html           Browser login form — credentials never pass through the agent
└── server.py                FastMCP server + ASGI app + /health + /login + /auth/status
```

**Transport:** Streamable HTTP at `/mcp` (for claude.ai web connectors) + SSE at `/sse`
**Auth:** Session file persisted to disk; survives server restarts (~24h lifetime)
**Login:** Browser-based — `zerodha_login()` MCP tool returns a URL; no credentials in tool params
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

## Phase 4.1 — Strategy Alignment

**Commit:** `9f72904`
**Tag:** `phase-4.1-strategy-alignment`
**Tools added:** 0 (modified `recommend_strategy` output) → **Total: 33**

### Problem

`recommend_strategy()` used only regime + RSI + ADX. It ignored the trade setup
signal entirely, producing contradictions like Signal: BUY / Strategy: Iron Condor
whenever `RANGE_BOUND` was detected — regardless of directional conviction.

### Fix

`recommend_strategy()` now calls `generate_trade_setup()` internally and applies
a signal-first priority order: **Signal > Regime > RSI > ADX**.

Conflict resolution rules:

| Signal | Regime | Primary | Secondary |
|---|---|---|---|
| BUY | RANGE_BOUND | Bull Call Spread | Iron Condor |
| SELL | RANGE_BOUND | Bear Put Spread | Iron Condor |
| NEUTRAL | RANGE_BOUND | Iron Condor | — |
| NEUTRAL_BULLISH | any | Bull Call Spread | — |
| NEUTRAL_BEARISH | any | Bear Put Spread | — |

### Output schema additions

```json
{
  "recommended": "Bull Call Spread",
  "secondary":   "Iron Condor",
  "signal":      "BUY",
  "regime":      "RANGE_BOUND",
  "reason":      "BUY signal overrides range-bound conditions..."
}
```

`"strategy"` key kept as backward-compatible alias for Dashboard consumers.

---

## Phase 5 — Trade Planner

**Commit:** `b0f099c`
**Tag:** `phase-5-trade-planner-complete`
**Tools added:** 1 → **Total: 34**

### Files created

| File | Purpose |
|---|---|
| `src/planner/__init__.py` | Package init |
| `src/planner/trade_plan.py` | Core logic — reuses all existing analysis functions |
| `src/tools/trade_planner.py` | 1 MCP tool registration |

### Design decisions

**Full reuse chain** — no calculations are duplicated:

```
create_trade_plan()
  ├── generate_trade_setup()    signal / entry / stoploss / target
  ├── recommend_strategy()      strategy + regime (signal-aware from 4.1)
  ├── calculate_risk_reward()   risk / reward / rr
  ├── calculate_position_size() quantity from capital + risk %
  └── _options_context()        pcr / max_pain (index only, silent on failure)
```

**Read-only** — does not place orders or call the Zerodha order API.

**Signal rules** — NEUTRAL returns `trade_allowed: false`.
NEUTRAL_BULLISH / NEUTRAL_BEARISH return cautious plans with reduced sizing guidance.

### Tools (1)

| Tool | Description |
|---|---|
| `create_trade_plan` | Entry / stoploss / target / position size / strategy for any symbol |

---

## Phase 5.1 — Trade Quality Filter

**Commit:** `e0cb0b2`
**Tag:** `phase-5.1-trade-quality-filter`
**Tools added:** 0 (modified `create_trade_plan` output) → **Total: 34**

### Problem

Trade planner returned actionable plans regardless of risk/reward quality.

### Fix

Added `trade_quality` field to `create_trade_plan()` output:

| RR | Quality |
|---|---|
| < 1.0 | LOW_QUALITY |
| 1.0–1.5 | MODERATE |
| 1.5–2.0 | GOOD |
| ≥ 2.0 | HIGH_QUALITY |

`trade_allowed` is set to `false` when quality is `LOW_QUALITY`.
Summary text is tier-aware and explains the quality assessment.

---

## Phase 5.2 — Risk/Reward Optimization

**Commit:** `cc910c9`
**Tag:** `phase-5.2-risk-reward-optimization`
**Tools added:** 0 (modified `generate_trade_setup` formulas) → **Total: 34**

### Root cause

Original ATR formula produced structural RR ≈ 0.71 for all setups:
- entry = price + 0.25×ATR, stoploss = price − 1.5×ATR, target = price + 1.5×ATR
- risk = 1.75×ATR, reward = 1.25×ATR → RR = 0.71 → always LOW_QUALITY

### Fix

Regime-aware target multipliers in `generate_trade_setup()`:

| Regime | Target ATR | Risk | Reward | RR |
|---|---|---|---|---|
| BULL_TREND / BEAR_TREND / BREAKOUT_POTENTIAL | 2.75× | 1.25× | 2.50× | 2.0 |
| NEUTRAL_BULLISH / NEUTRAL_BEARISH | 2.25× | 1.25× | 2.00× | 1.6 |
| RANGE_BOUND | 1.75× | 1.25× | 1.50× | 1.2 |

Stop tightened from 1.5×ATR to 1.0×ATR. Entry buffer unchanged at 0.25×ATR.

---

## Phase 6 — Option Strategy Builder

**Commit:** `f216db5`
**Tag:** `phase-6-option-strategy-builder-complete`
**Tools added:** 1 → **Total: 35**

### Files created

| File | Purpose |
|---|---|
| `src/strategy/__init__.py` | Package init |
| `src/strategy/builder.py` | Strike selection, payoff math, summary |
| `src/tools/strategy_builder.py` | 1 MCP tool registration |

### Design decisions

**Strike selection** — auto-detects strike interval from chain; selects ATM/ITM
strikes for directional legs, OI-based S/R for Iron Condor shorts (ATM±interval fallback).

**Real premiums** — uses `lastPrice` from the NSE option chain for all payoff
calculations when available. Sets `is_estimate: false` only when all leg premiums
are non-zero.

**Equity degradation** — `OptionsService.get_option_chain()` raises `RuntimeError`
for equity symbols (soft-blocked by NSE). The builder catches this and returns
`premium_data_available: false` with null payoffs and a clear summary.

**Payoff structures** — all 7 strategies implemented:

| Strategy | Max Loss | Max Profit | Breakeven |
|---|---|---|---|
| Bull Call Spread | net debit | spread − debit | buy strike + debit |
| Bear Put Spread | net debit | spread − debit | buy strike − debit |
| Long Call | premium | unlimited | strike + premium |
| Long Put | premium | strike − premium | strike − premium |
| Long Straddle | total premium | unlimited | strike ± total |
| Long Strangle | total premium | unlimited | each wing ± total |
| Iron Condor | max spread − credit | net credit | short legs ± credit |

### Tools (1)

| Tool | Description |
|---|---|
| `build_option_strategy` | Legs / premiums / max loss / max profit / breakeven from live NSE chain |

---

## Phase 7 — Trade Review Engine

**Commit:** `d3b4f82`
**Tag:** `phase-7-trade-review-engine-complete`
**Tools added:** 1 → **Total: 36**

### Files created

| File | Purpose |
|---|---|
| `src/review/__init__.py` | Package init |
| `src/review/reviewer.py` | Thesis evaluation, invalidation conditions, reasoning |
| `src/tools/trade_review.py` | 1 MCP tool registration |

### Design decisions

**Thesis status** — deterministic mapping from (direction, current signal):

| Direction | Signal | Thesis | Action |
|---|---|---|---|
| LONG | BUY | VALID | HOLD |
| LONG | NEUTRAL_BULLISH | WEAKENING | HOLD |
| LONG | NEUTRAL | WEAKENING | REDUCE |
| LONG | NEUTRAL_BEARISH / SELL | INVALIDATED | EXIT |
| SHORT | SELL | VALID | HOLD |
| SHORT | NEUTRAL_BEARISH | WEAKENING | HOLD |
| SHORT | NEUTRAL | WEAKENING | REDUCE |
| SHORT | NEUTRAL_BULLISH / BUY | INVALIDATED | EXIT |

**Invalidation conditions** — generated from live EMA20, EMA50, RSI values.
No LLM-generated opinions — same inputs always produce the same conditions.

**Optional P&L** — when `entry_price` is provided, `current_pnl_percent` is
calculated from the current price vs direction (LONG = (price − entry)/entry,
SHORT = (entry − price)/entry).

**Full reuse** — calls `detect_market_regime`, `generate_trade_setup`,
`recommend_strategy`, and `create_trade_plan`. No indicator math duplicated.

### Tools (1)

| Tool | Description |
|---|---|
| `review_trade` | HOLD / REDUCE / EXIT + thesis status + invalidation conditions |

---

## Phase 8 — Equity Option Chain Support

**Commit:** *(this commit)*
**Tag:** `phase-8-equity-option-chain-support`
**Tools added:** 1 → **Total: 37**

### Problem

`build_option_strategy()` and the options tools only worked for index symbols
(NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY). Equity symbols like RELIANCE or INFY
returned `premium_data_available: false` because the service passed `"NSE:RELIANCE"`
to jugaad's `equities_option_chain()`, which expects a bare symbol (`"RELIANCE"`).
The exchange prefix caused jugaad to return 0 rows → `RuntimeError` → graceful
degradation with null payoffs.

### Investigation (pre-implementation)

Test scripts confirmed:
- `NSELive.equities_option_chain("RELIANCE")` → 53 rows, real premiums ✓
- `NSELive.equities_option_chain("NSE:RELIANCE")` → 0 rows (root cause) ✓
- Row-level `expiryDates` (plural string) normalised to `expiryDate` by existing
  `_normalize()` — no change needed there
- RELIANCE, INFY, SBIN, IDEA all return live strikes, OI, IV, lastPrice

### Fix

Two-line change in `src/options/service.py`:

1. Added `_strip_exchange_prefix(symbol)` static method — `"NSE:RELIANCE"` → `"RELIANCE"`
2. Applied in `_fetch_via_jugaad()` (equity path only) and `_fetch_via_httpx()`

Index path (`NIFTY`, `BANKNIFTY`, etc.) is unchanged — these are already bare symbols.

### New tool

`get_equity_option_chain(symbol, expiry, atm_range=10)` — generic chain tool for
any NSE F&O equity. Same output schema as `get_nifty_option_chain`.

### Impact on existing tools

`build_option_strategy("NSE:RELIANCE")` now returns real strikes, premiums, and
payoff structures instead of degrading. The builder required no changes — the
service fix was sufficient.

### Tools (1)

| Tool | Description |
|---|---|
| `get_equity_option_chain` | CE/PE OI, IV, LTP for any NSE equity F&O symbol |

---

## Phase 10 — Market Intelligence Engine

**Commit:** `215c52f`
**Tag:** `phase-10-market-intelligence`
**Tools added:** 4 → **Total: 41**
**Tests added:** 91 (5 new files) → **Total: 361**

### Files created

| File | Purpose |
|---|---|
| `src/intelligence/__init__.py` | Package init |
| `src/intelligence/vix.py` | India VIX fetch, 52-week percentile, interpretation |
| `src/intelligence/global_pulse.py` | Crude, gold, DXY, S&P 500, US 10Y — sentiment |
| `src/intelligence/events.py` | Static economic calendar through 2027-03-31 |
| `src/intelligence/risk.py` | Composite 0–100 risk score from 4 components |
| `src/tools/intelligence.py` | 4 MCP tool registrations |
| `tests/test_intelligence_vix.py` | VIX unit + cache tests |
| `tests/test_intelligence_global.py` | Global pulse unit + cache tests |
| `tests/test_intelligence_events.py` | Events calendar unit + env-var override tests |
| `tests/test_intelligence_risk.py` | Risk score unit + integration tests |
| `tests/test_intelligence_regressions.py` | 5 named regression guards (IR-1 through IR-5) |

### Design decisions

**India VIX** — fetches `^INDIAVIX` via the existing `get_market().get_historical()` path
(yfinance-backed). Computes 52-week percentile by ranking today's level against the prior
252 trading days (today excluded from reference set). Interpretation buckets:

| VIX | Interpretation | Caution |
|---|---|---|
| < 12 | Complacency — historically precedes corrections | LOW |
| 12–15 | Calm — low fear, normal conditions | LOW |
| 15–20 | Mild uncertainty — some hedging activity | MODERATE |
| 20–25 | Elevated fear — market stress, increase caution | HIGH |
| > 25 | Extreme fear — major event or systemic stress | EXTREME |

**Global pulse** — 5 assets fetched individually via `get_historical` (2 candles each):
`CL=F` (crude), `GC=F` (gold), `DX-Y.NYB` (DXY), `^GSPC` (S&P 500), `^TNX` (US 10Y yield).
`overall_sentiment` is computed by a vote-based score: S&P 500 carries double weight;
RISK_OFF when ≥ 2 risk-off votes, RISK_ON when ≥ 2 risk-on votes, else NEUTRAL.

**Events calendar** — static `_STATIC` list embedded in `events.py` covering RBI MPC,
US FOMC, India CPI/GDP, and US NFP through 2027-03-31. An `UPCOMING_EVENTS_JSON`
env-var allows ad-hoc additions without code changes. `SCHEDULE_VALID_UNTIL` constant
triggers a log WARNING when within 30 days of expiry.

**Risk score composition** — four components, each scored 0–100:

| Component | Weight | Source |
|---|---|---|
| VIX caution level | 35% | `caution_level` from `get_india_vix()` |
| Event proximity | 30% | Days until nearest HIGH-impact event |
| PCR interpretation | 20% | Substring match against `analytics._pcr_sentiment()` strings |
| Market regime | 15% | `detect_market_regime()` mapped through `_REGIME_SCORES` |

Score is clamped to [0, 100]. Rating: LOW (<30), MODERATE (30–60), HIGH (60–80), EXTREME (≥80).
PCR component uses substring match against the exact interpretation strings from
`analytics.py` — not raw PCR thresholds — so the semantics remain consistent regardless
of future PCR threshold changes.

**Caching** — module-level TTL pattern (same as `options/service.py`):

| Module | TTL |
|---|---|
| `vix.py` | 300 s (5 min) |
| `global_pulse.py` | 300 s (5 min) |
| `events.py` | 3600 s (1 hour) |
| `risk.py` | 60 s (1 min) |

**Dashboard integration** — `build_dashboard()` calls `_intelligence_section()` in its
own try/except. Failure there does not break options, technicals, or analysis sections.
`_build_summary()` appends an event-warning sentence when a HIGH-impact event is within
3 days. The new `"intelligence"` key is always present in the dashboard response
(either a dict or `null` on failure).

**Trade planner integration** — `create_trade_plan()` exposes `risk_score` in its output
for visibility. It is wrapped in a try/except; it never affects `trade_allowed`,
position sizing, or any other trade logic.

### PCR interpretation → risk score mapping

```python
("bullish — elevated put writing", 10)   # pcr > 1.3
("mildly bullish",                 25)   # pcr > 1.0
("neutral to mildly bearish",      55)   # pcr > 0.7
("bearish — elevated call writing", 85)  # pcr <= 0.7
("insufficient data",              50)   # fallback
```

### Regression guards (IR-1 through IR-5)

| # | Class | Scenario protected |
|---|---|---|
| IR-1 | `TestIR1DashboardIntelligenceFailure` | Dashboard builds and returns `intelligence: null` when intelligence section raises |
| IR-2 | `TestIR2TradePlanRiskScoreFailure` | `create_trade_plan` succeeds when `_risk_score_context` raises; returns `risk_score: null` |
| IR-3 | `TestIR3SummaryBackwardCompat` | `_build_summary` works without `intelligence` arg; event warning only appended when event within 3 days |
| IR-4 | `TestIR4RiskScoreEmptyEvents` | Risk score returns valid 0–100 result with empty events list |
| IR-5 | `TestIR5RiskScorePcrUnavailable` | PCR component returns neutral 50 when options service raises; overall score still valid |

### Coverage

| Module | Coverage |
|---|---|
| `src/intelligence/events.py` | 97% |
| `src/intelligence/vix.py` | 98% |
| `src/intelligence/global_pulse.py` | 91% |
| `src/intelligence/risk.py` | 92% |

### Tools (4)

| Tool | Description |
|---|---|
| `get_india_vix` | VIX level, 52-week high/low, percentile rank, caution level, interpretation |
| `get_global_pulse` | Crude oil, gold, DXY, S&P 500, US 10Y — change %, India impact, overall sentiment |
| `get_upcoming_events` | RBI MPC, FOMC, India CPI/GDP, US NFP within N days |
| `get_market_risk_score` | Composite 0–100 risk score with factors, rating, recommendation |

---

## Phase 11B — Catalyst Intelligence

**Tag:** `phase-11b-catalyst-intelligence`
**Tools added:** 4 → **Total: 48**
**Tests added:** 124 (4 new files) → **Total: 551**

### Files created

| File | Purpose |
|---|---|
| `src/catalyst/__init__.py` | Package init |
| `src/catalyst/constants.py` | `_to_yf_ticker()`, keyword sets, `CATALYST_PRIORITY` |
| `src/catalyst/news.py` | `get_symbol_news()`, `_aggregate_sentiment()` |
| `src/catalyst/earnings.py` | `get_earnings_calendar()`, proximity scoring, corporate actions |
| `src/catalyst/event_risk.py` | `get_event_risk()`, confidence model, dual catalyst fields |
| `src/tools/catalyst.py` | 4 MCP tool registrations |
| `tests/test_catalyst_news.py` | 41 tests — symbol resolution, sentiment, news fetch |
| `tests/test_catalyst_earnings.py` | 38 tests — proximity, calendar parsing, actions parsing |
| `tests/test_catalyst_event_risk.py` | 28 tests — score formula, confidence model, catalysts |
| `tests/test_catalyst_regressions.py` | 17 tests — ER-1 through ER-5 regression guards |

### Design decisions

**Data source** — `yfinance.Ticker.news` (headlines), `.calendar` (earnings date + estimates),
`.actions` (dividends + splits). No API key required. Direct `yf.Ticker()` calls via a
patchable `_get_ticker()` factory in each module — tests patch this without touching the
existing market service.

**Symbol resolution** — `_to_yf_ticker()` in `constants.py` handles all forms:

| Input | Output |
|---|---|
| `INFY` | `INFY.NS` |
| `NSE:INFY` | `INFY.NS` |
| `INFY.NS` | `INFY.NS` (idempotent) |
| `NIFTY` | `^NSEI` |
| `BANKNIFTY` | `^NSEBANK` |

**Keyword sentiment** — pure Python, no ML, no external service. Keywords defined in
`constants.py` as `frozenset`. Per-article: positive hit count vs negative hit count
→ POSITIVE / NEGATIVE / NEUTRAL. Aggregate: `score = (pos − neg) / total` → −1.0 to +1.0.

**Sentiment → risk score mapping (for event_risk):**

| Sentiment | Score |
|---|---|
| VERY_POSITIVE (score > 0.3) | 10 |
| POSITIVE (0.1–0.3) | 25 |
| NEUTRAL (−0.1 to +0.1) | 45 |
| NEGATIVE (−0.3 to −0.1) | 65 |
| VERY_NEGATIVE (score < −0.3) | 90 |
| No articles | 45 (neutral) |

**Earnings proximity scoring:**

| Days until earnings | Risk label | Score |
|---|---|---|
| ≤ 1 | IMMINENT | 100 |
| ≤ 3 | VERY_HIGH | 80 |
| ≤ 7 | HIGH | 60 |
| ≤ 14 | MEDIUM | 30 |
| > 14 or None | LOW | 10 |

**Event risk composite (40/30/30):**

```
get_event_risk(symbol)
  ├── get_earnings_calendar(symbol)    40% — earnings proximity score
  ├── get_symbol_news(symbol)          30% — news sentiment → risk score
  │   └── _aggregate_sentiment()            (cached — no second yfinance fetch)
  └── get_market_risk_score(symbol)    30% — Phase 10 composite (VIX/events/PCR/regime)
```

**Confidence model** — reflects data availability:

| Sources available | Confidence |
|---|---|
| News + Earnings + Market | 1.0 |
| Any two sources | 0.8 |
| Market only | 0.5 |
| None | 0.3 |

**Dual catalyst fields:**

- `nearest_catalyst` — soonest catalyst by date within 30 days
- `highest_impact_catalyst` — highest-priority catalyst by `CATALYST_PRIORITY`:
  `EARNINGS=100`, `SPLIT=70`, `DIVIDEND=40`

These are not always the same: a dividend in 3 days and earnings in 20 days → nearest
is the dividend, highest impact is earnings.

**Property-access isolation** — `get_earnings_calendar()` accesses `ticker.calendar`
and `ticker.actions` in the outer try/except so yfinance exceptions surface as an
`"error"` key. Parse transformations are isolated in `_parse_calendar()` /
`_parse_actions()` which accept raw objects (not the ticker itself) — this separation
is what enables ER-1 and ER-4 regression guards to work correctly.

**Cache TTLs:**

| Module | TTL |
|---|---|
| `news.py` | 1800 s (30 min) |
| `earnings.py` | 3600 s (1 hour) |
| `event_risk.py` | 300 s (5 min) |

**Index symbols** — `get_earnings_calendar("NIFTY")` returns `earnings_proximity_risk: "N/A"`
and a `note` field. `get_symbol_news("NIFTY")` returns market-wide news (useful as macro filter).

### Regression guards (ER-1 through ER-5)

| # | Class | Scenario protected |
|---|---|---|
| ER-1 | `TestER1YfinanceRaises` | yfinance raises → `{"error": "..."}` from news/earnings; event_risk stays valid |
| ER-2 | `TestER2EmptyNewsList` | Empty news → `count: 0`, `headlines: []`, sentiment is NEUTRAL |
| ER-3 | `TestER3NoCalendarData` | `Ticker.calendar` returns None → `next_earnings_date: null`, `earnings_proximity_risk: "LOW"` |
| ER-4 | `TestER4AllFetchesFail` | News + earnings both fail → event_risk uses market score only, `confidence: 0.5` |
| ER-5 | `TestER5SymbolNormalization` | `INFY`, `NSE:INFY`, `INFY.NS` all resolve to `INFY.NS` — idempotent, no duplication |

### Coverage

| Module | Coverage |
|---|---|
| `src/catalyst/constants.py` | 100% |
| `src/catalyst/news.py` | 92% |
| `src/catalyst/earnings.py` | 83% |
| `src/catalyst/event_risk.py` | 91% |

### Tools (4)

| Tool | Auth | Description |
|---|---|---|
| `get_symbol_news` | — | Recent headlines with per-article sentiment (POSITIVE/NEGATIVE/NEUTRAL) |
| `get_news_sentiment` | — | Aggregate sentiment score + counts from cached news (no second fetch) |
| `get_earnings_calendar` | — | Next earnings date, EPS estimate, upcoming dividends + splits |
| `get_event_risk` | — | Composite 0–100 event risk: earnings proximity + news + market risk |

---

## Phase 12 — Trade Journal Foundation

**Commit:** `83f22cb`
**Tag:** `phase-12-trade-journal`
**Tools added:** 4 → **Total: 52**
**Tests added:** 110 (3 new files) → **Total: 661**

### Files created

| File | Purpose |
|---|---|
| `src/journal/__init__.py` | Package init |
| `src/journal/db.py` | SQLite connection factory, schema DDL, `reset_connection()` test seam |
| `src/journal/service.py` | CRUD + P&L — log_trade, close_trade, get_open_trades, get_trade_history |
| `src/tools/journal.py` | 4 MCP tool registrations |
| `tests/test_journal_db.py` | Schema init, indexes, connection factory, schema version (17 tests) |
| `tests/test_journal_service.py` | CRUD, P&L, tags, snapshot, summary (68 tests) |
| `tests/test_journal_regressions.py` | JR-1 through JR-5 regression guards (25 tests) |

### Design decisions

**SQLite, no external services** — `sqlite3` from the Python standard library. File path from
`JOURNAL_DB` env var (default: `journal.db`). On Railway, mount a persistent volume and set
`JOURNAL_DB=/data/journal.db` — otherwise the journal is lost on container restart.

**Schema v1 (30 columns):**

| Column | Type | Notes |
|---|---|---|
| `id` | TEXT PK | Raw UUID4 hex, aliased to `trade_id` in all API responses |
| `symbol` | TEXT | Uppercased at write time |
| `trade_type` | TEXT | DEFAULT `'EQUITY'` — EQUITY / OPTIONS / FUTURES / INDEX |
| `direction` | TEXT | `'LONG'` or `'SHORT'` (case-normalised at write) |
| `entry_price` | REAL | Required; validated > 0 |
| `stoploss` / `target` | REAL | Optional; `risk_reward` auto-calculated if both provided |
| `risk_reward` | REAL | Explicit value takes precedence over auto-calculated |
| `regime` / `signal` / `risk_score` | TEXT/INT | Context from prior analysis calls — not auto-fetched |
| `analysis_snapshot` | TEXT | JSON blob — any additional analysis context at entry |
| `created_by` | TEXT | DEFAULT `'MANUAL'` — MANUAL / CLAUDE / AUTOMATED |
| `status` | TEXT | `'OPEN'` or `'CLOSED'` only |
| `exit_reason` | TEXT | TARGET_HIT / STOPLOSS_HIT / MANUAL / THESIS_INVALIDATED / EXPIRED / CANCELLED |
| `pnl` / `pnl_percent` / `holding_days` | REAL/INT | Calculated on `close_trade()` |
| `tags` | TEXT | JSON array; returned as Python list |
| `created_at` / `updated_at` | TEXT | ISO-8601 UTC datetime |

**Trade IDs:** `TRD-` + 8 lowercase hex chars from `uuid4().hex[:8]`.
Short enough to copy-paste for `close_trade()`. Collision probability < 0.01% at 10,000 trades.

**P&L calculation:**

```python
# LONG:  pnl = (exit - entry) * qty;  pct = (exit - entry) / entry * 100
# SHORT: pnl = (entry - exit) * qty;  pct = (entry - exit) / entry * 100
# quantity=None defaults to 1 for pnl; pnl_percent is always per-unit
```

**risk_reward auto-calculation:**

```python
# LONG:  reward = target - entry;  risk = entry - stoploss
# SHORT: reward = entry - target;  risk = stoploss - entry
# risk <= 0 → None (no auto-calc; e.g. stoploss above entry for LONG)
```

**Context fields (regime, signal, risk_score, analysis_snapshot)** are purely optional.
The MCP client (Claude) populates them from prior `detect_market_regime` /
`get_market_risk_score` / `get_event_risk` calls already in the conversation session.
`log_trade` does not auto-call any analysis tools — this avoids coupling journal writes to
network I/O and keeps `log_trade` always fast and available.

**`analysis_snapshot`** is a free-form JSON dict for any extra context the caller wants to
preserve at entry time (e.g. `{"vix": 14.2, "event_risk": 42, "pcr": 1.1}`). Stored as
JSON string, returned as a parsed Python dict.

**Error isolation** — every service function wraps its body in `try/except Exception` and
returns `{"error": str(exc)}`. No exception propagates to the MCP caller.

**Testability seam** — `db.reset_connection(conn)` injects a connection directly into the
module-level `_conn` global. All tests call this with `sqlite3.connect(":memory:")` before
each test class, giving every test a fresh isolated in-memory database. Service functions
access the connection via `_db._get_connection()` (module-reference lookup, not direct
import) so `monkeypatch.setattr(journal_db, "_get_connection", _fail)` reaches service.py
correctly.

**WAL mode** — `PRAGMA journal_mode=WAL` enables concurrent reads while writes are
serialised by a module-level `_WRITE_LOCK = threading.Lock()` in `service.py`.

**notes append semantics** — `close_trade(notes=...)` appends to existing notes with a
newline separator. Passing `notes=None` leaves existing notes unchanged.

**status is binary** — only `OPEN` or `CLOSED`. `CANCELLED` is a valid `exit_reason` value
(records a trade that was entered but abandoned), not a separate status value. This keeps
P&L filtering simple: `WHERE status = 'CLOSED'` captures all finalised trades regardless of
exit reason.

### get_trade_history summary

```json
{
  "summary": {
    "total_trades": 12,
    "open_trades": 2,
    "closed_trades": 10,
    "win_count": 6,
    "loss_count": 4,
    "win_rate_pct": 60.0,
    "total_pnl": 4850.0,
    "avg_pnl": 485.0,
    "avg_holding_days": 3.8,
    "best_trade":  {"trade_id": "TRD-c7f2a1b0", "symbol": "TCS",  "pnl": 2100.0},
    "worst_trade": {"trade_id": "TRD-d9e0b3a2", "symbol": "IDEA", "pnl": -640.0}
  }
}
```

`win_count` = closed trades with `pnl > 0`. `avg_pnl` and `avg_holding_days` are over
closed trades only. `best_trade` / `worst_trade` are `null` when no closed trades exist in
the filtered result set.

### Indexes

```sql
idx_trades_symbol      ON trades(symbol)
idx_trades_status      ON trades(status)
idx_trades_entry_date  ON trades(entry_date)
idx_trades_trade_type  ON trades(trade_type)
```

### Migration strategy

Schema version tracked in `schema_version` table (v1 on first init). Future phases add
columns via `ALTER TABLE` + `_migrate()` function in `db.py`. The `_init_schema()` function
is idempotent (`CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`).

### Regression guards (JR-1 through JR-5)

| # | Class | Scenario protected |
|---|---|---|
| JR-1 | `TestJR1LogTradeMinimal` | `log_trade` with only required fields → valid `trade_id`, no crash |
| JR-2 | `TestJR2CloseNonExistent` | `close_trade` with unknown `trade_id` → `{"error": "trade not found: ..."}`, no exception |
| JR-3 | `TestJR3DatabaseFailure` | DB connection raises → `{"error": "..."}` from all 4 service functions |
| JR-4 | `TestJR4DoubleClose` | `close_trade` on already-closed trade → error dict, original `exit_price` unchanged |
| JR-5 | `TestJR5HistoryDaysZero` | `get_trade_history(days=0)` → valid empty result, no SQL error |

### Coverage

| Module | Coverage |
|---|---|
| `src/journal/db.py` | 92% |
| `src/journal/service.py` | 93% |

### Tools (4)

| Tool | Auth | Description |
|---|---|---|
| `log_trade` | — | Record a new trade; returns `trade_id` (TRD-xxxxxxxx) |
| `close_trade` | — | Finalise a position; calculates pnl, pnl_percent, holding_days |
| `get_open_trades` | — | List open positions, optional symbol filter |
| `get_trade_history` | — | Query history with filters + performance summary |

---

## Phase 13 — Trade Recommendation Engine

**Tag:** `phase-13-trade-recommendation`
**Tools added:** 3 → **Total: 55**
**Tests added:** 84 (2 new files) → **Total: 745**

### Files created

| File | Purpose |
|---|---|
| `src/recommendations/__init__.py` | Package init |
| `src/recommendations/engine.py` | All recommendation logic |
| `src/tools/recommendations.py` | MCP tool registration |
| `tests/test_recommendations_engine.py` | 60 unit tests: TestRecommendTrade, TestReviewOpenTrades, TestGetDailyBrief |
| `tests/test_recommendations_regressions.py` | 24 regression guards: RR-1 through RR-5 + extras |

### Files modified

| File | Change |
|---|---|
| `src/server.py` | Added `recommendations` import + `.register(mcp)` + instruction block |
| `CLAUDE.md` | Phase 13 complete, 55 tools, 745 tests |
| `PROJECT_STATE.md` | Phase 13 entry, tool count, tag, recent changes |
| `DEVELOPMENT.md` | This section |

### Tools

| Tool | Auth | Description |
|---|---|---|
| `recommend_trade(symbol, capital, risk_percent)` | — | Portfolio-aware ENTER/WAIT/AVOID with direction, sizing, event risk, VIX context |
| `review_open_trades()` | — | Live review of all open journal positions: HOLD/REDUCE/EXIT per position |
| `get_daily_brief()` | — | Morning briefing: VIX + global sentiment + risk score + position review + alerts |

### Design decisions

**Module composition (reuse only):**
- `recommend_trade` calls `create_trade_plan` (signal + sizing), `get_event_risk` (catalyst gating),
  `get_india_vix` (volatility gating), `get_open_trades` (duplicate exposure check)
- `review_open_trades` calls `get_open_trades` + `review_trade` per position
- `get_daily_brief` calls `review_open_trades`, `get_india_vix`, `get_market_risk_score`,
  `get_global_pulse`, `get_upcoming_events`
- Zero new indicator code; zero new data sources

**Gating logic:**
- Event risk ≥80 → `trade_allowed=False`, recommendation=AVOID
- Event risk 60–79 → size ×0.70, caution added, recommendation=WAIT (if no other block)
- VIX EXTREME → `trade_allowed=False`, recommendation=AVOID
- VIX HIGH → caution only (no size reduction)
- Duplicate exposure (same symbol + same direction in journal) → size ×0.50, recommendation=WAIT
- Size factors stack multiplicatively; floor at 1 (never zero quantity)

**Monkeypatch-friendly import pattern:**
All external function imports use module-level alias names (`_get_open_trades`, `_create_trade_plan`,
etc.) so `monkeypatch.setattr(rec_engine, "_fn", mock)` reaches the call site at runtime.
`get_daily_brief` calls `review_open_trades()` as a local name — patched via
`monkeypatch.setattr(rec_engine, "review_open_trades", mock)`.

**Error isolation:**
- `recommend_trade`: `_get_event_risk` and `_get_india_vix` failures → field set to `None`, call continues
- `review_open_trades`: per-position `_review_trade` failure → position `error` field set, others continue
- `get_daily_brief`: each `market_context` sub-call in its own `try/except` → field set to `None` or `[]`
- Top-level `try/except` on all three functions: unexpected errors return `{"error": str(exc)}`

**`stoploss_breached` / `target_reached` direction-aware:**
- LONG: breached when `current_price <= stoploss`; reached when `current_price >= target`
- SHORT: breached when `current_price >= stoploss`; reached when `current_price <= target`
- `None` stoploss/target → never breached/reached (guarded by `bool(stoploss and ...)`)

### Regression guards

| # | Class | Protection |
|---|---|---|
| RR-1 | `TestRR1PlanImmutability` | `recommend_trade` must not mutate the plan dict |
| RR-2 | `TestRR2SizeFactorFloor` | `_apply_size_factors` always returns ≥1, never 0 |
| RR-3 | `TestRR3DailyBriefGracefulDegradation` | All market_context calls failing → no top-level error |
| RR-4 | `TestRR4ReviewActionKey` | Uses `"action"` key, not `"review_action"` |
| RR-5 | `TestRR5TradeplanErrorPropagation` | Error from `create_trade_plan` propagated as `{"error": ...}` |

### Git tag

```
phase-13-trade-recommendation
```

---

## Complete Tool Registry (55 tools)

### Authentication (2)
`zerodha_login`, `check_auth_status`

### Account & Portfolio (4) — require active session
`get_profile`, `get_holdings`, `get_positions`, `get_margins`

### Market Data (7) — no auth
`get_quote`, `get_ohlc`, `get_ltp`, `get_historical_data`,
`get_instruments`, `search_instruments`, `invalidate_instruments_cache`

### Options & Derivatives (8) — no auth
`get_expiries`, `get_nifty_option_chain`, `get_banknifty_option_chain`,
`get_equity_option_chain`, `calculate_pcr`, `get_oi_analysis`,
`identify_support_resistance_from_oi`, `calculate_max_pain`

### Technicals (6) — no auth
`calculate_rsi`, `calculate_ema`, `calculate_macd`,
`calculate_adx`, `calculate_atr`, `analyze_technicals`

### Analysis (5) — no auth
`detect_market_regime`, `generate_trade_setup`, `recommend_strategy`,
`calculate_risk_reward`, `calculate_position_size`

### Dashboard (2) — no auth
`get_nifty_dashboard`, `get_banknifty_dashboard`

### Trade Planner (1) — no auth
`create_trade_plan`

### Option Strategy Builder (1) — no auth
`build_option_strategy`

### Trade Review (1) — no auth
`review_trade`

### Market Intelligence (4) — no auth
`get_india_vix`, `get_global_pulse`, `get_upcoming_events`, `get_market_risk_score`

### Portfolio Intelligence (3) — require active session
`get_portfolio_risk_report`, `get_portfolio_regime_analysis`, `get_portfolio_exposure_breakdown`

### Catalyst Intelligence (4) — no auth
`get_symbol_news`, `get_news_sentiment`, `get_earnings_calendar`, `get_event_risk`

### Trade Journal (4) — no auth
`log_trade`, `close_trade`, `get_open_trades`, `get_trade_history`

### Trade Recommendations (3) — no auth
`recommend_trade`, `review_open_trades`, `get_daily_brief`

---

## Phase 9 — Automated Testing & Regression Protection

**Tag:** `phase-9-automated-testing`
**Tests:** 270 passed, 0 failed
**Run:** `uv run pytest tests/ -v`

### Test files

| File | Scope |
|---|---|
| `tests/conftest.py` | Shared fixtures, tech snapshots, chain_data, patch helpers |
| `tests/test_options.py` | `options/analytics.py` pure math + `OptionsService._strip_exchange_prefix` |
| `tests/test_technicals.py` | `technical/indicators.py` — RSI, EMA, MACD, ADX, ATR |
| `tests/test_analysis.py` | Regime detection, trade setup, strategy recommendation |
| `tests/test_planner.py` | Trade quality classification, `create_trade_plan` integration |
| `tests/test_strategy_builder.py` | Payoff math, leg selection, all 7 strategies |
| `tests/test_review.py` | `_evaluate` mapping, invalidation conditions, `review_trade` integration |
| `tests/test_dashboard.py` | `_build_summary` pure tests, `build_dashboard` error isolation |
| `tests/test_regressions.py` | 7 named regression guards (see below) |

### Coverage

| Module | Coverage |
|---|---|
| `src/analysis/regime.py` | 88% |
| `src/strategy/builder.py` | 92% |
| `src/planner/trade_plan.py` | 86% |
| `src/review/reviewer.py` | 84% |
| `src/dashboard/service.py` | 85% |
| `src/technical/indicators.py` | 92% |
| `src/options/analytics.py` | 100% |

### Regression guards

| # | Class | Bug protected |
|---|---|---|
| 1 | `TestReg1SymbolNormalization` | `NSE:RELIANCE` prefix passed verbatim to jugaad → 0 rows |
| 2 | `TestReg2BuyRangeBoundConflict` | BUY + RANGE_BOUND returned Iron Condor, not Bull Call Spread |
| 3 | `TestReg3SellRangeBoundConflict` | SELL + RANGE_BOUND returned Iron Condor, not Bear Put Spread |
| 4 | `TestReg4LegacySchema` | `generate_trade_setup` dropped `entry`/`stoploss`/`target` scalar fields |
| 5 | `TestReg5ZoneSchema` | Zone fields (`entry_above` etc.) dropped in some signal paths |
| 6 | `TestReg6TradeQualityFilter` | RR < 1 returned `trade_allowed=True` |
| 7 | `TestReg7EquityOptionChain` | `build_option_strategy("NSE:RELIANCE")` returned `premium_data_available=False` |

### Mock strategy

All tests use `monkeypatch` — no live NSE/Yahoo Finance/Zerodha calls:

- Patch `src.analysis.regime._analyze_technicals` → controls the entire analysis chain deterministically
- Patch `get_options_service` → returns a class that raises `RuntimeError` (silently handled by `_options_context`)
- `_fetch_via_jugaad` tested by injecting a `FakeNSELive` via `OptionsService.__new__`

---

## Phase 11A — Portfolio Intelligence

**Commit:** *(current)*
**Tag:** `phase-11a-portfolio-intelligence`
**Tools added:** 3 → **Total: 44**
**Tests added:** 66 (2 new files) → **Total: 427**

### Files created

| File | Purpose |
|---|---|
| `src/portfolio_intelligence/__init__.py` | Package init |
| `src/portfolio_intelligence/service.py` | All aggregation logic — no duplicated indicators |
| `src/tools/portfolio_intelligence.py` | 3 MCP tool registrations |
| `tests/test_portfolio_intelligence.py` | Unit + integration tests |
| `tests/test_portfolio_intelligence_regressions.py` | PR-1 through PR-5 regression guards |

### Design decisions

**Reuse chain — no new logic:**

```
get_portfolio_risk_report()
  ├── get_broker().holdings()           demat positions (always LONG)
  ├── get_broker().positions()["net"]   intraday/carry-forward overlay
  ├── review_trade(sym, dir, entry)     action + thesis_status + regime + signal
  └── get_market_risk_score(sym)        composite 0–100 risk per symbol

get_portfolio_exposure_breakdown()
  └── _get_all_positions()              raw broker data only — no analysis calls
```

**Position unification:** Holdings (demat) take priority. Net positions are added only for symbols not already in holdings. If a symbol appears in both, the holding entry is used (longer-term view; intraday overlay ignored). Deduplication is by `tradingsymbol`.

**Direction mapping:** Holdings → always `LONG`. Net position → `LONG` if qty > 0, `SHORT` if qty < 0. `review_trade` receives the correct direction for each.

**Portfolio risk score:** Value-weighted average of per-position `get_market_risk_score()` results. Weight = `current_value` (qty × last_price). Falls back to simple average when all values are zero, and to neutral 50 when no scores are available.

**Diversification score (HHI-based):**

```
score = round((1 - Σ(sᵢ²)) × 100)   where sᵢ = position_value / total_value
```

| Positions | Result |
|---|---|
| 1 (fully concentrated) | 0 |
| 2 equal | 50 |
| 10 equal | 90 |

**Concentration risk:** Flags any single position > 30% of total portfolio value.

**Error isolation:** Per-position: `review_trade` and `get_market_risk_score` each wrapped in try/except. Failed symbols appear with `review_action: null`, `risk_score: null` — they do not suppress other positions. Broker calls wrapped at the top: failure returns `{"error": "..."}` from all three tools, no unhandled exception.

### Regression guards (PR-1 through PR-5)

| # | Class | Scenario protected |
|---|---|---|
| PR-1 | `TestPR1EmptyPortfolio` | Empty holdings + positions → valid structured response with zero counts |
| PR-2 | `TestPR2BrokerAuthFailure` | Broker raises (no session) → `{"error": "..."}` from all three tools, no exception |
| PR-3 | `TestPR3PerSymbolAnalysisFailure` | One symbol's review_trade raises → other positions still analyzed and returned |
| PR-4 | `TestPR4AllAnalysisFailed` | All per-symbol calls fail → exposure keys still valid; risk score falls back to neutral 50 |
| PR-5 | `TestPR5SymbolDeduplication` | Same symbol in holdings AND net positions → appears once, holding data used |

### Coverage

| Module | Coverage |
|---|---|
| `src/portfolio_intelligence/service.py` | 97% |

### Tools (3)

| Tool | Auth | Description |
|---|---|---|
| `get_portfolio_risk_report` | ✓ | Per-position risk scores + portfolio risk + diversification + recommendations |
| `get_portfolio_regime_analysis` | ✓ | Regime distribution + directional bias across all holdings |
| `get_portfolio_exposure_breakdown` | ✓ | Long/short exposure, largest position, concentration metrics (fast, no analysis) |

---

## Git Tags

| Tag | Commit | Description |
|---|---|---|
| `phase-3-analysis-complete` | `a3907e3` | Analysis + schema reconciliation complete |
| `phase-4-dashboard-complete` | `6c30ce6` | Dashboard complete — final Phase 4 state |
| `phase-4.1-strategy-alignment` | `9f72904` | Signal-priority conflict resolution in recommend_strategy |
| `phase-5-trade-planner-complete` | `b0f099c` | create_trade_plan — full read-only trade plan |
| `phase-5.1-trade-quality-filter` | `e0cb0b2` | trade_quality classification by RR ratio |
| `phase-5.2-risk-reward-optimization` | `cc910c9` | Regime-aware ATR multipliers — RR 1.2–2.0 |
| `phase-6-option-strategy-builder-complete` | `f216db5` | build_option_strategy — strikes + payoffs |
| `phase-7-trade-review-engine-complete` | `d3b4f82` | review_trade — HOLD/REDUCE/EXIT + thesis |
| `phase-8-equity-option-chain-support` | `<prev>` | get_equity_option_chain — real strikes/premiums for NSE equities |
| `phase-9-automated-testing` | *(prev)* | 270 tests, 80%+ coverage on all business-logic modules |
| `phase-10-market-intelligence` | `215c52f` | Market Intelligence Engine — VIX, global pulse, events, risk score; 41 tools, 361 tests |
| `phase-11a-portfolio-intelligence` | *(prev)* | Portfolio Intelligence — risk report, regime analysis, exposure breakdown; 44 tools, 427 tests |
| `phase-11b-catalyst-intelligence` | `e157948` | Catalyst Intelligence — news, earnings, event risk; 48 tools, 551 tests |
| `phase-12-trade-journal` | `83f22cb` | Trade Journal Foundation — SQLite journal, P&L, summary; 52 tools, 661 tests |
| `phase-13-trade-recommendation` | *(prev)* | Trade Recommendation Engine — recommend_trade, review_open_trades, get_daily_brief; 55 tools, 745 tests |
| `phase-14-position-sizing` | *(prev)* | Position Sizing Engine — size_equity_trade, size_options_trade, size_from_recommendation; 58 tools, 852 tests |
| `phase-14.5-reliability-hardening` | *(prev)* | Reliability Hardening — NaN propagation fix, RSI tiers, confidence cap, gating cautions; 58 tools, 867 tests |
| `phase-14.6-consistency-hardening` | *(prev)* | Consistency & Data-Source Hardening — symbol unification, event-risk confidence gating, degradation flags, one confidence scale, common package, data_basis/staleness; 58 tools, 1011 tests |
| `phase-15a-journal-analytics` | `cd872be` | Journal Performance Analytics — get_performance_analytics: realized win-rate / avg-P&L / profit-factor by signal, regime, confidence band; 59 tools, 1030 tests |
| `phase-15b-turso-migration` | `2b55dcb` | Journal Persistence — Turso cloud SQLite via libsql_experimental; linux-only dep; _LibsqlConn wrapper; 59 tools, 1030 tests |
| `phase-16-zerodha-auto-import` | `b539a8e` | Zerodha Trade Auto-Import — sync_trades_from_zerodha, get_orders, schema v3 external_id; 61 tools, 1053 tests |
| `phase-17-calibration-engine` | `6f3c21c` | Calibration Engine — Brier score, reliability curve, overconfidence analysis; 62 tools, 1081 tests |
| `phase-18-feedback-loop` | `3e6a516` | Recommendation Feedback Loop — self-correcting confidence, calibration-based sizing; 62 tools, 1129 tests |
| `phase-19-multiframe-confirmation` | `231cccc` | Multi-timeframe Regime Confirmation — get_regime_alignment, weekly conflict detection in recommend_trade; 63 tools, 1179 tests |
| *(no tag — research phase)* | `64539c4` | Phase 20A Regime Predictiveness Audit — walk-forward audit framework, run-start diagnostics, negative finding on EMA+ADX; 63 tools, 1222 tests |

---

## Phase 14 — Position Sizing Engine

**Tag:** `phase-14-position-sizing`
**Tools added:** 3 → **Total: 58**
**Tests added:** 107 → **Total: 852**

### What was built

- 3 new tools: `size_equity_trade`, `size_options_trade`, `size_from_recommendation`
- New `src/sizer/` package: `engine.py` (all logic), `src/tools/sizer.py` (MCP registration)
- `size_equity_trade`: quantity = max(1, floor(risk\_budget / stoploss\_distance)); direction-aware for LONG/SHORT
- `size_options_trade`: lots = max(1, floor(risk\_budget / (premium\_distance × lot\_size))); caution when capital\_at\_risk > 5%
- `size_from_recommendation`: calls `recommend_trade()` → uses its position\_size as base; applies ONLY portfolio heat on top (Phase 13 factors already applied)
- Portfolio heat: sum of open trade risks from journal / capital; stoploss-absent trades use 2% default
- Heat ELEVATED (≥7%) → size ×0.75; CRITICAL (≥9%) → size ×0.50; stacks with portfolio risk report score
- Portfolio risk HIGH (≥75) → ×0.75; EXTREME (≥90) → ×0.50; broker auth failure → factor silently skipped
- All factors stack multiplicatively via `_apply_size_factors`; floor at 1
- `size_from_recommendation` returns AVOID with null sizing fields and null `log_trade_params` (no accidental logging)
- `log_trade_params` returned by all 3 tools; keys validated against `log_trade()` signature
- Journal schema v1 → v2: adds `risk_amount REAL`, `capital_at_risk REAL`, `portfolio_heat_at_entry REAL`
- Migration via ALTER TABLE ADD COLUMN; idempotent try/except per statement; version stamp updated
- Immutability rule: `risk_amount`, `capital_at_risk`, `portfolio_heat_at_entry` set at entry, never modified
- `log_trade()` gains 3 new optional params; all callers unaffected
- 107 new tests across 2 files; PS-1 through PS-5 regression guards
- Zero changes to existing 55 tools; no regressions

---

## Phase 14.5 — Reliability Hardening

**Tag:** `phase-14.5-reliability-hardening`
**Tools added:** 0 → **Total: 58 (unchanged)**
**Tests added:** 15 → **Total: 867**

### What was built

No new tools. Targeted hardening of the data validation and scoring layer.

Root causes confirmed via codebase audit:
- `float(np.nan)` from yfinance NaN rows was not filtered, propagating through Wilder smoothing as `float('nan')` rather than `None`. `NaN ≠ None` in Python, so `None in (...)` guards did not catch it.
- RSI > 70 (overbought) was not penalized — RSI 74 scored identically to RSI 56, producing confidence of 100 in some configurations.
- Silent `except Exception: pass` in `recommend_trade` swallowed event\_risk and VIX fetch failures, proceeding without gating data and without informing the caller.

### Changes

| Fix | File | Description |
|---|---|---|
| Fix 1 | `src/market/service.py` | NaN rows from yfinance filtered in `get_historical()` before building candle list |
| Fix 2a | `src/analysis/regime.py` | `_is_invalid()` helper returns True for None and float NaN; applied at both indicator guard sites |
| Fix 2b | `src/analysis/regime.py` | `_validate_number()` rejects NaN via `math.isnan()` |
| Fix 3 | `src/tools/technicals.py` | `analyze_technicals` returns error when any primary indicator is NaN |
| Fix 4 | `src/analysis/regime.py` | RSI > 70 → bearish +10 (overbought); RSI < 30 → bullish +10 (oversold) instead of amplified directional signal |
| Fix 5 | `src/analysis/regime.py` | Confidence capped at `min(85, ...)` in `generate_trade_setup` — no indicator model warrants 100% |
| Fix 6 | `src/recommendations/engine.py` | Event risk and VIX fetch failures surface as cautions; `gating_data_available` field added |
| Fix 7 | `src/tools/technicals.py` | Docstrings clarify lookback period differences (60d/120d vs 150d in `analyze_technicals`) |

### New tests

| File | Class | Tests |
|---|---|---|
| `tests/test_technicals.py` | `TestNaNPropagation` | `test_nan_close_produces_nan_rsi`, `test_nan_high_produces_nan_adx` |
| `tests/test_analysis.py` | `TestIsInvalid` | 4 tests for `_is_invalid()` helper |
| `tests/test_analysis.py` | `TestDetectMarketRegime` | `test_regime_returns_error_for_nan_rsi` |
| `tests/test_analysis.py` | `TestGenerateTradeSetup` | `test_rsi_overbought_adds_bearish_not_bullish`, `test_rsi_oversold_adds_bullish_not_bearish` |
| `tests/test_recommendations_engine.py` | `TestGatingDataUnavailable` | 3 gating caution tests |
| `tests/test_regressions.py` | RH-1, RH-2, RH-3 | NaN→error, confidence≤85, overbought regression guards |

### Backward compatibility

All 58 tools unchanged. `recommend_trade` gains additive `gating_data_available` field. `confidence` maximum changes from 100 to 85 (no caller should gate on `confidence == 100`).

---

## Phase 14.6 — Consistency & Data-Source Hardening

**Tag:** `phase-14.6-consistency-hardening`
**Tools added:** 0 → **Total: 58 (unchanged)**
**Tests added:** 144 → **Total: 1011**

### What was built

A post-release audit of Phase 14.5 surfaced a second tier of correctness,
consistency, and data-source issues. No new tools — targeted hardening only.

**Tier A — correctness**
- **A0** Lock-in tests for the 14.5 fixes that previously had no test on their real
  code path: a NaN-bearing DataFrame through `get_historical` (Fix 1) and the
  `analyze_technicals` MCP tool's NaN guard (Fix 3). Both could have silently
  regressed.
- **A1** Unified symbol resolution into `src/market/symbols.py` (single source of
  truth). Three divergent `_INDEX_YF` tables (market/technicals/catalyst) had let
  the same alias resolve differently or break — e.g. `get_quote("NIFTY")` resolved
  to a bad ticker while `calculate_rsi("NIFTY")` worked. Catalyst keeps its
  NSE-centric equity rule (BSE→.NS) but shares the canonical index table.
- **A2** `recommend_trade` now reads `event_risk.confidence`. `get_event_risk`
  never raises and falls back internally, so the engine was hard-gating AVOID on
  fabricated low-confidence scores; gating now only applies at confidence ≥ 0.5,
  otherwise a caution is raised and `gating_data_available.event_risk` is False.
- **A3** `get_market_risk_score` now reports `confidence`, `is_degraded`, and
  `degraded_components`. A score built entirely from neutral fallbacks no longer
  masquerades as a reliable MODERATE.

**Tier B — consistency / single source of truth**
- **B1** One confidence scale (0–85) everywhere. The setup tally is *rescaled*
  into the band (not clamped — preserves resolution), regime confidence shares the
  ceiling, and the dead `min(100, …)` in the reviewer is removed.
- **B2** New `src/common/` package: `scoring.py` (`risk_rating`,
  `apply_size_factors`) and `signals.py` (signal sets + `direction_from_signal`).
  Removed the duplicated rating bands (risk + event_risk) and size-factor math
  (recommendations + sizer). Regime names are now a canonical `REGIMES` frozenset
  in regime.py, with a test guarding `_REGIME_SCORES` coverage.
- **B3** PCR risk scoring keys on a stable `pcr_sentiment_code` from
  `calculate_pcr`, not the human-readable interpretation prose — display copy can
  change without silently breaking the risk score.
- **B4** `recommend_trade` and the trade plan now surface a `data_basis`
  (source, candles_used, last_candle_date, staleness_days), and a caution is added
  when the last EOD candle is more than 5 days old.

**Tier C — robustness polish**
- **C1** `_analyze_technicals` is cached per `(symbol, lookback)` for 60s, so a
  single recommend/review flow fetches once and every layer sees the same candle
  snapshot (no mid-call divergence; removes the ~8-fetch redundancy in
  `review_trade`). `clear_analysis_cache()` is an autouse test seam.
- **C2** Near-boundary cautions: RSI within 2 points of 30/70, and event risk
  within 5 of the binary AVOID gate, are flagged as unstable/borderline.
- **C3** Property/shape tests for scoring: confidence ceiling across an input
  sweep, RSI-overbought monotonicity (the YES BANK regression), and `risk_rating`
  monotonicity.
- **C4** `get_historical` docstring documents the `auto_adjust=True` (adjusted)
  price basis and its implication for absolute entry/stop/target levels.

### New files

| File | Purpose |
|---|---|
| `src/market/symbols.py` | Canonical symbol resolution |
| `src/common/scoring.py` | Shared `risk_rating`, `apply_size_factors` |
| `src/common/signals.py` | Signal taxonomy + `direction_from_signal` |
| `tests/test_market_service.py` | get_historical NaN filter + symbol resolution |
| `tests/test_common.py` | Shared primitives + regime-coverage guard |
| `tests/test_scoring_properties.py` | Monotonicity / ceiling property tests |

### Backward compatibility

All 58 tools unchanged. `recommend_trade` gains additive `event_risk_confidence`
and `data_basis` fields; `get_market_risk_score` gains `confidence`/`is_degraded`/
`degraded_components`; `calculate_pcr` gains `pcr_sentiment_code`. Confidence
values for RSI<70 setups shift slightly (rescaled 0–85 vs former clamp), but the
field range and BUY/SELL thresholds are unchanged.

---

## Phase 15A — Journal Performance Analytics

**Tag:** `phase-15a-journal-analytics`
**Tools added:** 1 → **Total: 59**
**Tests added:** 19 → **Total: 1030**

### What was built

A realized-outcome feedback loop — the first thing that measures whether the
analysis model actually has edge, rather than asserting it. Read-only; reuses the
existing journal schema (no new storage, no persistent recommendation log).

- New tool `get_performance_analytics(symbol=None, days=365, min_sample=10)` and
  `journal.service.get_performance_analytics`.
- Buckets CLOSED trades by `signal`, `regime`, and entry-confidence band
  (`high (75-85)` / `moderate (60-74)` / `low (<60)` / `unknown`, read from
  `analysis_snapshot.confidence`). Each bucket reports trades, wins,
  win_rate_pct, avg_pnl, total_pnl, low_sample.
- `overall` adds `profit_factor` = gains / |losses| (`null` when no losses —
  JSON-safe, never `inf`).
- `notes` surface a confidence-calibration check (do high-confidence trades win
  more than low-confidence ones?) and small-sample warnings (buckets below
  `min_sample` are flagged `low_sample` so a thin journal isn't over-read).
- Only `status == "CLOSED"` trades count; open trades are excluded everywhere.
  Legacy rows without a recorded confidence degrade gracefully into `"unknown"`.

### Tool (1)

| Tool | Auth | Description |
|---|---|---|
| `get_performance_analytics` | — | Realized win-rate / avg-P&L / profit-factor by signal, regime, and confidence band, with calibration + sample-size notes |

### Coverage

`journal/service.py` 96%; new function near-fully exercised (19 tests, incl. MCP
registration). No tools or tests modified elsewhere.

---

## Phase 15B — Journal Persistence (Turso cloud SQLite)

**Commits:** `2b55dcb`, `c6bca46`
**Tag:** `phase-15b-turso-migration`
**Tools added:** 0 → **Total: 59**
**Tests added:** 0 → **Total: 1030**

### What was built

Migrated the trade journal from ephemeral local SQLite (lost on every Railway redeploy) to
[Turso](https://turso.tech) cloud-hosted libSQL — same SQL dialect, no schema changes, free tier
(9 GB / 1B row reads / month, permanent).

### Files changed

| File | Change |
|---|---|
| `src/journal/db.py` | Branches on `TURSO_DATABASE_URL`: libsql_experimental (Turso) when set, local sqlite3 fallback when unset. Added `_LibsqlConn` + `_LibsqlCursor` wrappers. |
| `pyproject.toml` | Added `libsql-experimental>=0.0.6; sys_platform == 'linux'` — Railway (Linux) installs it; Windows skips and uses sqlite3 fallback. |
| `.env.example` | Documents `TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN`. |

### Design decisions

**libsql_experimental compatibility** — the package does not support `conn.row_factory`, so a
thin wrapper (`_LibsqlConn` / `_LibsqlCursor`) was added that:
- intercepts `execute()` and wraps the raw cursor
- converts tuple rows to dicts using `cursor.description` column names
- exposes `fetchone()` / `fetchall()` returning dict rows (compatible with `dict(row)` in `service.py`)

**Platform marker** — `libsql-experimental` has no pre-built Windows wheel and requires Rust
compilation. Using `sys_platform == 'linux'` keeps the Railway deploy clean while letting
local Windows dev continue with sqlite3.

**Zero test changes** — tests inject an in-memory sqlite3 connection via `reset_connection()`.
That seam is unchanged; all 1030 tests pass against the sqlite3 path as before.

**New env vars:**

| Variable | Purpose |
|---|---|
| `TURSO_DATABASE_URL` | `libsql://your-db.turso.io` — activates Turso path when set |
| `TURSO_AUTH_TOKEN` | JWT token from `turso db tokens create <db>` |

Leave both blank for local sqlite3 fallback.

---

## Phase 16 — Zerodha Trade Auto-Import

**Commit:** `b539a8e`
**Tag:** `phase-16-zerodha-auto-import`
**Tools added:** 2 → **Total: 61**
**Tests added:** 23 (1 new file) → **Total: 1053**

### What was built

Automatic sync of executed Zerodha orders into the trade journal — no manual `log_trade` calls needed after placing trades.

### Files changed

| File | Change |
|---|---|
| `src/broker/zerodha_web.py` | Added `orders()` → `GET /api/orders`, `trades()` → `GET /api/trades` |
| `src/broker/base.py` | Added `orders()` and `trades()` to `BrokerClient` Protocol |
| `src/broker/jugaad.py` | Added `orders()` / `trades()` stubs (raise `NotImplementedError`) |
| `src/journal/db.py` | Schema v3: `external_id TEXT` column + `idx_trades_external_id`; migrations run before indexes |
| `src/journal/service.py` | Extended `log_trade` with `external_id`, `entry_date`, `entry_time`; added `sync_zerodha_orders`, `_find_open_long_for_symbol`, `_parse_order_timestamp`, `_product_to_trade_type` |
| `src/tools/journal.py` | 2 new MCP tools: `get_orders`, `sync_trades_from_zerodha` |
| `tests/test_journal_sync.py` | 23 new tests covering helpers + sync logic |
| `tests/test_sizer_engine.py` | Updated `TestSchemaMigration` to use `_SCHEMA_VERSION` constant (not hardcoded 2) |

### Design decisions

**Idempotent via `external_id`** — Zerodha's `order_id` is stored in `external_id` on each imported BUY. Re-running sync skips any order already in the journal. SELL closure is naturally idempotent: once the matched LONG is CLOSED, no subsequent SELL finds it.

**BUY/SELL matching logic:**

```
for each COMPLETE order (sorted by timestamp):
  BUY  → check external_id not in journal → log_trade(LONG, external_id=order_id)
  SELL → find most recent open LONG for same symbol → close_trade()
         if no open LONG found → unmatched_sells (reported, not an error)
```

**Trade type detection (`_product_to_trade_type`):**

| Zerodha product | Symbol suffix | Result |
|---|---|---|
| CNC / MIS | any | EQUITY |
| NRML | ends with `CE`/`PE` AND digit before | OPTIONS |
| NRML | ends with `FUT` | FUTURES |
| any | other | EQUITY |

The digit-before check prevents equity symbols like `RELIANCE` (ends in `CE`) from being misclassified.

**Schema migration ordering** — `_init_schema` was restructured to run migrations before creating indexes. Previously, index creation on `external_id` failed on v1/v2 databases because the column didn't exist yet when the index was attempted.

**Timestamp preservation** — `log_trade` gains optional `entry_date` / `entry_time` overrides so imported trades record the Zerodha order timestamp, not the sync time.

**`created_by = "ZERODHA_SYNC"`, `tags = ["zerodha-import"]`** — imported trades are distinguishable from manually logged ones in history and analytics.

### Sync response schema

```json
{
  "imported": 3,
  "closed": 2,
  "skipped": 1,
  "unmatched_sells": 0,
  "errors": 0,
  "details": {
    "imported": [{"order_id": "...", "symbol": "RELIANCE", "trade_id": "TRD-...", "price": 2500, "qty": 10}],
    "closed":   [{"order_id": "...", "symbol": "RELIANCE", "trade_id": "TRD-...", "pnl": 500, "exit_price": 2550}],
    "skipped":  [{"order_id": "...", "symbol": "INFY", "reason": "already_imported"}],
    "unmatched_sells": [],
    "errors": []
  }
}
```

### Tools (2)

| Tool | Auth | Description |
|---|---|---|
| `get_orders` | ✓ | Fetch today's Zerodha orders; filterable by status (default: complete) |
| `sync_trades_from_zerodha` | ✓ | Import today's executed orders into journal; idempotent |

---

## Phase 17 — Calibration Engine

**Commit:** `6f3c21c`
**Tag:** `phase-17-calibration-engine`
**Tools added:** 1 → **Total: 62**
**Tests added:** 28 (1 new file) → **Total: 1081**

### What was built

Proper scoring rule (Brier score) to measure whether the model's stated confidence
values actually predict trade outcomes — answering "when the model says 75% confident,
does it win 75% of the time?"

### Files created

| File | Purpose |
|---|---|
| `src/calibration/__init__.py` | Package init |
| `src/calibration/service.py` | `get_calibration_report` + 4 private helpers |
| `src/tools/calibration.py` | 1 MCP tool registration |
| `tests/test_calibration.py` | 28 unit + integration tests |

### Files modified

| File | Change |
|---|---|
| `src/server.py` | Added `calibration` import + `calibration.register(mcp)` |

### Design decisions

**Brier score** — `mean((confidence/85 − outcome)²)` where `confidence` is read from
`analysis_snapshot.confidence` and `outcome` is 1 for a win (pnl > 0) or 0 for a loss.
The `/85` normalises to [0, 1] probability space using the system-wide confidence ceiling.
Only trades with a recorded confidence contribute to the score — trades logged without it
are reported in `notes` as a percentage but excluded from the calculation.

**Rating thresholds:**

| Brier Score | Rating |
|---|---|
| ≤ 0.15 | EXCELLENT |
| ≤ 0.20 | GOOD |
| ≤ 0.25 | FAIR |
| > 0.25 | POOR |

**Reliability curve** — groups closed trades into confidence buckets, then computes
per-bucket average predicted probability vs actual win rate and their difference:

```
calibration_gap = actual_win_rate − avg_predicted_probability
  positive → underconfident (model undersells its accuracy)
  negative → overconfident  (model oversells its accuracy)
```

Buckets below `min_sample` (default 5) are flagged `low_sample` so thin data doesn't
mislead. The `unknown` bucket captures trades with no recorded confidence.

**Overconfidence analysis** — aggregates directional bias across non-low-sample buckets:

```
overconfidence_score  = mean(|negative gaps|)   # how much model over-predicts
underconfidence_score = mean(positive gaps)      # how much model under-predicts
dominant_bias = OVERCONFIDENT | UNDERCONFIDENT | BALANCED
```

**Phase 18 reuse** — three helpers are designed for direct reuse by the Recommendation
Feedback Loop (Phase 18):

| Helper | Purpose |
|---|---|
| `_calculate_brier_score(trades)` | Brier score + rating over any trade list |
| `_build_reliability_curve(trades, min_sample)` | Per-bucket curve data |
| `_calibration_gap(actual, predicted)` | Single-gap calculation |

These are internal to `calibration/service.py` — not exported as MCP tools.

**Reuses existing primitives** — `_confidence_of()` and `_row_to_dict()` imported
directly from `src/journal/service.py` to avoid duplicating confidence extraction logic.

### Tool (1)

| Tool | Auth | Description |
|---|---|---|
| `get_calibration_report` | — | Brier score, reliability curve, and overconfidence bias over closed journal trades |

### Example output

```json
{
  "brier_score": 0.18,
  "calibration_rating": "GOOD",
  "brier_scored_trades": 45,
  "reliability_curve": [
    {"bucket": "high",     "trade_count": 18, "avg_predicted_probability": 0.894, "actual_win_rate": 0.778, "calibration_gap": -0.116, "low_sample": false},
    {"bucket": "moderate", "trade_count": 20, "avg_predicted_probability": 0.741, "actual_win_rate": 0.700, "calibration_gap": -0.041, "low_sample": false},
    {"bucket": "low",      "trade_count":  7, "avg_predicted_probability": 0.565, "actual_win_rate": 0.571, "calibration_gap":  0.006, "low_sample": false}
  ],
  "overconfidence_analysis": {
    "overconfidence_score": 0.0785,
    "underconfidence_score": 0.006,
    "dominant_bias": "OVERCONFIDENT"
  },
  "trade_count": 52,
  "notes": ["7% of trades have no confidence score (logged without analysis_snapshot.confidence)."]
}
```

---

## Phase 18 — Recommendation Feedback Loop

**Commit:** `3e6a516`
**Tag:** `phase-18-feedback-loop`
**Tools added:** 0 → **Total: 62 (unchanged)**
**Tests added:** 48 (2 new files) → **Total: 1129**

### What was built

The system's recommendations become self-correcting: instead of trusting the model's
raw confidence scores, recommendations now use what historical performance actually
shows. A model that claims 80% confidence but wins only 65% of the time will have
its trades sized down automatically.

### Files created

| File | Purpose |
|---|---|
| `src/feedback/__init__.py` | Package init |
| `src/feedback/calibration_adjustment.py` | Core helpers: `get_calibrated_confidence`, `calibration_size_factor` |
| `tests/test_feedback.py` | 30 unit + integration tests |
| `tests/test_feedback_regressions.py` | 18 regression guards FB-1 through FB-7 |

### Files modified

| File | Change |
|---|---|
| `src/planner/trade_plan.py` | Fetches calibration report post-plan; adds `raw_confidence`, `calibrated_confidence`, `confidence_adjustment`, `calibration_applied` to output |
| `src/recommendations/engine.py` | Imports `calibration_size_factor`; reads calibration fields from plan; applies size factor; adds calibration fields to return dict |

### Design decisions

**Single calibration fetch** — `create_trade_plan` fetches `get_calibration_report()` once.
`recommend_trade` calls `create_trade_plan` and reads the calibration fields from the plan —
no second fetch. The journal query runs exactly once per recommendation flow.

**Calibration bucket matching:**

| Raw confidence | Bucket used |
|---|---|
| ≥ 75 | `high` |
| 60–74 | `moderate` |
| < 60 | `low` |

The bucket's `actual_win_rate` (from Phase 17 reliability curve) is converted back
to the 0–85 confidence space: `calibrated = actual_win_rate × 85`.

**Minimum sample gate** — 20 trades per bucket required before calibration activates.
Below that threshold, `calibration_applied=False` and the raw confidence is used unchanged.
This is stricter than Phase 17's default `min_sample=5` because Phase 18 acts on the output
(position sizing) rather than just reporting it.

**Position size adjustment via existing `apply_size_factors()`:**

| Calibrated confidence | Factor | Effect |
|---|---|---|
| ≤ 45 | ×0.50 | Halve position |
| ≤ 55 | ×0.75 | Reduce 25% |
| 56–74 | ×1.00 | No change |
| ≥ 75 | ×1.10 | Increase 10% |

Applied in `recommend_trade` only (not in `create_trade_plan`) so the factor appears
once in `risk_adjustments` and is never compounded (FB-7). Stacks correctly with
event-risk and duplicate-exposure factors via the existing `apply_size_factors()` chain.

**Backward compatibility** — the existing `confidence` key in both `create_trade_plan`
and `recommend_trade` responses is unchanged (raw model confidence). The four new keys
(`raw_confidence`, `calibrated_confidence`, `confidence_adjustment`, `calibration_applied`)
are purely additive. All 62 tools remain unchanged (FB-6).

**Graceful degradation** — the calibration fetch in `create_trade_plan` is wrapped in
`try/except`. Any failure (DB unreachable, no history, insufficient sample) sets
`calibration_applied=False` and the plan proceeds with the raw confidence unmodified.

### Regression guards (FB-1 through FB-7)

| # | Class | Scenario protected |
|---|---|---|
| FB-1 | `TestFB1NoCalibrationHistoryRecommendationUnchanged` | Empty curve → `calibration_applied=False`, size unchanged |
| FB-2 | `TestFB2LowSampleBucketNoCalibration` | Bucket below 20 trades → `calibration_applied=False` |
| FB-3 | `TestFB3MissingConfidenceCalibrationSkipped` | `actual_win_rate=None` → raw confidence used |
| FB-4 | `TestFB4AdjustedConfidenceNeverBelowZero` | `calibrated_confidence` always ≥ 0 |
| FB-5 | `TestFB5AdjustedConfidenceNeverAbove85` | `calibrated_confidence` always ≤ 85 |
| FB-6 | `TestFB6ExistingSchemaUnchanged` | All existing response keys present in both tools |
| FB-7 | `TestFB7PositionSizeReductionAppliedOnce` | Calibration factor appears once, not compounded |

---

## Phase 20A — Regime Predictiveness Audit (Research)

**Commit:** `64539c4` — `feat(research): Phase 20A regime predictiveness audit`
**Tag:** *(none — research phase, no MCP tools added)*
**Tests at end of phase:** 1222 (1195 existing + 27 new)
**Tools added:** 0 (research infrastructure, no new MCP tools)

### What was built

- `scripts/regime_audit.py` — walk-forward audit framework for regime model evaluation
  - Sliding 150-candle window, advancing day-by-day from 2022-01-01 through 2025-12-11
  - `_build_technicals()`: pure mirror of `_analyze_technicals()` with no I/O — uses pre-downloaded candles
  - `run_symbol_audit()`: per-symbol walk-forward loop with warmup, tail exclusion, and closure guards
  - `compute_metrics()`: per-regime n, runs, avg run length, directional accuracy, avg forward returns (5/10/20d)
  - `run_start_vs_continuation()`: splits each regime run into entry day vs continuation days to distinguish mature-trend effect from inception failure
  - `monotonicity_check()`: validates expected BULL > NEUTRAL_BULLISH > RANGE_BOUND > NEUTRAL_BEARISH > BEAR ordering
  - `print_run_diagnostic()`: inline interpretation labels for each diagnostic outcome
- `tests/test_regime_audit.py` — 27 regression tests
  - Guards: no `detect_market_regime` calls, no live I/O in inner loop
  - Boundary guards: warmup, tail exclusion, CLASSIFY_FROM
  - `TestRunStartVsContinuation`: 11 tests covering all four interpretation outcomes

### Finding (negative result)

| Metric | Result |
|---|---|
| BULL_TREND aggregate 10d return | -0.354% |
| BULL_TREND run-start 10d return | -0.608% |
| BEAR_TREND aggregate 10d return | +0.316% |
| Monotonicity | Violated |
| Inception failure | 3 of 4 equities |

The current EMA20/EMA50 + ADX > 25 regime engine does not demonstrate directional
predictive value for NSE equities over the 2022-2025 test window. Run-start returns
are negative across most symbols, ruling out the mature-trend/late-signal hypothesis.
This is an inception failure: the classification logic does not identify positive-return
environments at the moment of entry.

The audit framework is retained for evaluating future regime models.

### Symbols tested

`^NSEI`, `INFY.NS`, `HDFCBANK.NS`, `RELIANCE.NS`, `TATAMOTORS.NS`

### Methodology constraints enforced

| Constraint | Implementation |
|---|---|
| No lookahead | Forward returns computed only within `max_classify_idx = n - 1 - TAIL_EXCLUSION` |
| Warmup | First LOOKBACK-1 indices skipped; CLASSIFY_FROM date gate applied |
| No live I/O in loop | `_build_technicals()` uses pre-downloaded slice; tested by 3 guard tests |
| Closure-in-loop safety | `_fwd()` captures `i` and `close_t` via default argument |
| Production parity | Indicator construction mirrors `_analyze_technicals()` exactly |

---

## Phase 22 — Decision Quality Measurement

**Date:** 2026-06-20
**Tools at end of phase:** 68 (5 new)
**Tests:** 1318 (86 new, 0 failures)
**North star:** Measure whether the MCP improves decision quality — not market prediction.

### What was built

#### Hotfix — Symbol Normalizer (`src/market/symbols.py`)
- `normalize_symbol(symbol, tool) -> (normalized: str, was_corrected: bool)`
- Per-tool format map (`_TOOL_FORMATS`): `get_quote` → `NSE:{symbol}`, `analyze_technicals` → `{symbol}.NS`, `detect_market_regime` → bare `{symbol}`, etc.
- Index aliases (NIFTY, BANKNIFTY…) pass through `INDEX_YF` regardless of tool
- Bug: used `removesuffix` not `rstrip` — `rstrip(".NS")` strips chars, mangling tickers like "TCS" → "TC"

#### Commit 1 — Trust Metadata (`src/meta.py`)
All MCP tool responses now return `{"data": <existing output>, "meta": <trust context>}`.

**Meta fields:**
- `type`: FACT | INDICATOR | INTERPRETATION | PREDICTION (PREDICTION = deprecated)
- `validation.status`: VERIFIED | MATHEMATICALLY_COMPUTED | UNVALIDATED | DEPRECATED
- `data_quality`: VALID | NaN_DETECTED | STALE | PARTIAL | INVALID
- `market_hours`: True during NSE session 09:15–15:30 IST
- `source`: NSELive | yfinance | internal_journal | zerodha_api
- `account_type`: MARKET_DATA_ONLY | PAPER_JOURNAL
- `deprecated_fields_present`, `deprecation_note`
- `symbol_corrected`, `symbol_original`
- `bootstrap_period`, `warning`, `limitations`, `as_of`

**`detect_data_quality(data)`:** checks for NaN values, USD tickers (price < 1), staleness > 5 days via `data_basis.staleness_days`.

**Wrapped tools:** market (get_quote, get_ohlc, get_ltp, get_historical_data), technicals (all 6), analysis (all 6), journal (all 7).

Existing tests test the service layer directly — no test breakage from wrapping. Only 3 tests that used the tool wrapper layer directly were updated.

#### Commit 2 — DB Schema v4 (`src/journal/db.py`)
New `recommendation_log` table:

| Column group | Fields |
|---|---|
| Always trusted | timestamp, symbol, market_snapshot (JSON), mcp_facts (JSON), user_action, outcome_1d/5d/20d |
| Claude layer | claude_reasoning_summary, recommendation_type, uncertainty_level |
| Decision tracking | mcp_changed_decision, would_have_acted_without_mcp |
| Process quality | decision_quality (JSON: process_followed, risk_defined, position_sized_correctly, exit_plan_defined) |
| Postmortem | postmortem_helpful, postmortem_why, postmortem_review_questions (JSON: 6 fields) |
| Partition flags | bootstrap_period=1 (default), bias_contaminated=1 (default), baseline_no_mcp=0 (default), capture_mode |

**Views:** `clean_recommendations` (bootstrap=0, bias=0), `baseline_decisions` (baseline_no_mcp=1), `bootstrap_records` (bootstrap=1 OR bias=1).

**Partition constants:**
- `BOOTSTRAP_PERIOD_RECORDS = 50`
- `BASELINE_RECORDS_REQUIRED = 10`
- `MIN_CLEAN_RECORDS_FOR_ANALYSIS = 100`

Schema version 3 → 4. Migration: `recommendation_log` created via `IF NOT EXISTS` — no ALTER needed for existing DBs.

#### Commit 3 — Logger Service + Tools
**`src/recommendation_log/service.py`:**
- `log_recommendation(symbol, user_question, market_snapshot, mcp_facts, claude_reasoning_summary, recommendation_type, uncertainty_level, baseline_no_mcp) → dict`
  - Returns record with `id` (format: `REC-xxxxxxxx`)
  - All outcome fields NULL at creation
  - `bootstrap_period=1`, `bias_contaminated=1` always at creation
- `update_recommendation_outcome(id, user_action, mcp_changed_decision, ..., postmortem_review_questions) → dict`
  - Partial updates only (non-None fields only)
  - Called during weekly review, NOT at trade time
- `get_recommendation_stats(clean_only=True) → dict`
  - Returns partition counts + `analysis_ready` bool
  - `stats=None` until `MIN_CLEAN_RECORDS_FOR_ANALYSIS` + `BASELINE_RECORDS_REQUIRED` met
- `get_recommendation_by_id(id) → dict`

**`src/tools/recommendation_log.py`** — 5 new MCP tools:
- `log_recommendation` — capture a Claude recommendation after giving it
- `update_recommendation_outcome` — fill postmortem during weekly review
- `get_recommendation_stats` — partition counts + readiness
- `get_full_market_context(symbol, include_options=False)` — single call replacing 6 separate calls; returns quote + OHLC + technicals + regime + VIX + upcoming events; include_options adds OI S/R levels
- `detect_recommendation(text)` — scan text for trigger phrases (returns metadata, does NOT auto-log)

#### Commit 4 — Auto-capture (`src/recommendation_log/capture.py`)
`detect_recommendation(text) → dict` scans for 40+ trigger phrases across 9 recommendation types (ENTER/EXIT/HOLD/AVOID/STAY_CASH/SIZE_REDUCE/TAKE_PROFIT/TIGHTEN_STOP/OBSERVE). Returns `dominant_type`, `triggers_found[]`, `requires_logging`, `capture_mode='auto'`. Does NOT auto-log.

#### Commit 5 — Deprecation Flags
`detect_market_regime` and `generate_trade_setup` now emit `deprecated_fields_present: ["confidence", "signal"]` and a `deprecation_note` citing Phase 20A and Phase 21 negative findings. Fields remain present for backward compatibility. Removal scheduled for Commit 6 (2 weeks later, manual decision).

### Commit 6 — completed in Phase 22F (see Phase 22F section below)
Field deletion and `market_structure` conversion were completed in commit `0d849cf`.
`confidence`, `signal`, `trade_quality`, `quality`, `bullish_probability`, `regime` deleted.
`market_structure` boolean descriptor added. `schema_version: 5` in meta permanently.

### Weekly review ritual (human process, not code)
1. Open `recommendation_log` on Sunday
2. For each unreviewed record: read `market_snapshot` + `mcp_facts` first
3. Answer 6 postmortem questions BEFORE reading `claude_reasoning_summary` (blind review)
4. Fill postmortem fields via `update_recommendation_outcome`
5. Do NOT draw conclusions before 100 clean records

### New tool registry additions

| Tool | Module | Description |
|---|---|---|
| `log_recommendation` | recommendation_log | Log a Claude recommendation for later review |
| `update_recommendation_outcome` | recommendation_log | Fill postmortem during weekly review |
| `get_recommendation_stats` | recommendation_log | Partition counts + analysis readiness |
| `get_full_market_context` | recommendation_log | Single-call market context (replaces 6 calls) |
| `detect_recommendation` | recommendation_log | Scan text for recommendation triggers |

### Test files added

| File | Tests | Coverage |
|---|---|---|
| `tests/test_phase22_meta.py` | 32 | src/meta.py — all public functions |
| `tests/test_phase22_symbols.py` | 13 | normalize_symbol() |
| `tests/test_phase22_recommendation_log.py` | 41 | service CRUD, detect_recommendation, stats |

---

## Phase 22F — Field Deletion + market_structure Conversion

**Date:** 2026-06-20
**Commit:** `0d849cf`
**Tools:** 68 (unchanged)
**Tests:** 1366 (48 new, 0 failures)

### What was built

Phase 22 Commit 6 — the deletion of synthetic conviction fields and conversion to honest structural descriptors. Transformation applied at the **tool layer only**; service layer (`src/analysis/regime.py`) is unchanged, preserving internal consumers (dashboard, planner, recommendations engine).

#### Deleted fields (both tools)
`confidence`, `signal`, `trade_quality`, `quality`, `bullish_probability`, `regime`

These fields had no demonstrated predictive validity (Phase 20A: no walk-forward edge; Phase 21: negative momentum spreads). Fully removed — not flagged.

#### `detect_market_regime` → `market_structure` descriptor

**Before:**
```json
{ "regime": "BULL_TREND", "confidence": 82, ... }
```

**After:**
```json
{
  "market_structure": {
    "price": 24512.3, "ema20": 24380.1, "ema50": 24120.8, "adx": 31.4, "rsi": 66.2,
    "price_above_ema20": true, "ema20_above_ema50": true,
    "adx_above_25": true, "rsi_above_60": true,
    "descriptor": ["price_above_ema20", "ema20_above_ema50", "adx_above_25", "rsi_above_60"],
    "indicator_interpretation": {
      "type": "INTERPRETATION", "validation_status": "UNVALIDATED",
      "adx_note": "trend_present", "rsi_note": "momentum_elevated"
    }
  },
  "_migration": { "regime_removed": true, "replacement": "market_structure", "schema_version": 5 }
}
```

Descriptor array is **always auto-generated** from booleans — never hardcoded. ADX notes: `trend_absent` (<15), `trend_weak` (<25), `trend_present` (<35), `strong_trend_present` (≥35). RSI notes: `oversold` (<30), `momentum_low` (<45), `momentum_neutral` (<55), `momentum_elevated` (<70), `overbought` (≥70).

#### `generate_trade_setup` — stripped fields
`confidence` and `signal` deleted. `reasoning` strings containing `NEUTRAL_BULLISH`/`NEUTRAL_BEARISH` removed (they encoded directional bias in prose). Kept: `entry`, `stoploss`, `target`, `entry_above`, `entry_below`, `bull_target`, `bear_target`, `reasoning`, `data_basis`, `_migration`.

#### `schema_version: 5` in meta (permanent)
Added to every `build_meta()` response. Carried in `result["meta"]["schema_version"]` going forward. `_migration` block in tool data is **temporary** — remove in Phase 23.

#### Docstrings embed research findings
Both `detect_market_regime` and `generate_trade_setup` docstrings now cite Phase 20A and Phase 21 findings so future Claude sessions cannot forget what was already disproved.

### Files changed

| File | Change |
|---|---|
| `src/meta.py` | `schema_version: 5` added to `build_meta()` |
| `src/tools/analysis.py` | `_build_market_structure()`, `_clean_generate_setup()`, updated docstrings, `flag_deprecated` removed |
| `tests/test_phase22f.py` | 48 new tests (new file) |
| `CLAUDE.md` | Phase, test count, constraints updated |

### Test file added

| File | Tests | Coverage |
|---|---|---|
| `tests/test_phase22f.py` | 48 | field deletion, market_structure, booleans, descriptor, indicator_interpretation, _migration, schema_version, forbidden words, docstrings, regressions |

#### Reasoning decontamination (commit `c9a64f6`)

`generate_trade_setup` tool no longer forwards the service-layer reasoning (which contained predictive language like "aligning with bullish setups", "ADX confirms directional conviction"). A new `_generate_reasoning()` function produces 5 observation-only sentences derived from `market_structure`:

```
"Price (101.0) is above EMA20 (100.00)."
"EMA20 (100.00) is above EMA50 (90.00)."
"ADX is 30.00 (above the 25 threshold): trend_present."
"RSI is 65.00: momentum_elevated."
"Current market structure includes: price_above_ema20, ema20_above_ema50, adx_above_25, rsi_above_60."
```

The philosophy comment is encoded directly above the function:
- **MAY:** describe current state, summarize indicator values, reference descriptors
- **MAY NOT:** predict future movement, recommend a direction, imply probability, imply edge

`generate_trade_setup` output now includes `market_structure` alongside `entry/stoploss/target`. The tool calls both `regime.generate_trade_setup()` and `regime.detect_market_regime()` — the `_analyze_technicals` TTL cache prevents a second network fetch.

### Files changed (full phase)

| File | Change |
|---|---|
| `src/meta.py` | `schema_version: 5` added to `build_meta()` |
| `src/tools/analysis.py` | `_build_market_structure()`, `_generate_reasoning()`, updated docstrings, tool layer transformation |
| `tests/test_phase22f.py` | 57 new tests (new file) |
| `CLAUDE.md` | Phase, test count, constraints updated |

### Test files added

| File | Tests | Coverage |
|---|---|---|
| `tests/test_phase22f.py` | 57 | field deletion, market_structure, booleans, descriptor, indicator_interpretation, _migration, schema_version, forbidden words, reasoning decontamination, docstrings, regressions |

### TODO Phase 23
- Remove `_migration` block from `detect_market_regime` and `generate_trade_setup` output
- Rename `bull_target`/`bear_target` → `upside_reference_level`/`downside_reference_level` (deferred from 22F)
- Only `meta["schema_version"]` stays permanently

---

## Browser Login (Phase 22G)

**Commit:** `e0fc8b0`
**Tools changed:** 1 (zerodha_login) — no new tools; total stays 68
**Files changed:** `src/tools/auth.py`, `src/server.py`, `ui/login.html`, `README.md`

### Problem

`zerodha_login(user_id, password, totp_code)` passed credentials as MCP tool parameters.
Any MCP client (Claude, Cursor, ChatGPT connector, custom agent) could see, log, or include
them in context history. Credential-in-param is the standard vulnerability in naïve MCP auth.

### Solution

`zerodha_login()` now takes **no parameters**. It returns:

```json
// When not authenticated:
{
  "authenticated": false,
  "login_url": "https://zerodha-mcp-production.up.railway.app/login",
  "message": "Open login_url in your browser..."
}

// When already authenticated:
{
  "authenticated": true,
  "message": "Already authenticated."
}
```

The agent tells the user to open the URL. Credentials are typed directly into the server's
HTML form — they never appear in MCP traffic, agent context, or tool logs.

### Routes added to server.py

| Route | Method | Purpose |
|-------|--------|---------|
| `/login` | GET | Serves `ui/login.html` with optional `ZERODHA_USER_ID` pre-fill |
| `/login` | POST | Parses form, calls `broker.login()`, saves `.session.json`, returns result page |
| `/auth/status` | GET | JSON `{authenticated, backend}` for non-agent status checks |

### Security properties

- Password and TOTP fields use `<input type="password">` — not echoed to DOM
- Error responses never repeat submitted field values
- `PUBLIC_URL` env var controls the login URL the tool returns (defaults to `http://localhost:8000`)
- Auto-login on startup from `ZERODHA_*` env vars remains — Railway env vars are private to the server

### What did NOT change

- Auto-login from `ZERODHA_USER_ID` + `ZERODHA_PASSWORD` + `ZERODHA_TOTP_SECRET` env vars on startup
- `.session.json` session persistence
- `check_auth_status()` MCP tool
- All 67 other tools
- All 1375 tests pass

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
| Signal-strategy conflicts | Signal takes priority over regime in recommend_strategy (Phase 4.1) |
| Structurally poor RR | Regime-aware ATR multipliers in generate_trade_setup (Phase 5.2) |
| Equity option chains | Strip exchange prefix (NSE:RELIANCE→RELIANCE) before calling jugaad equities_option_chain |
| Dashboard intelligence failure isolation | `_intelligence_section()` wrapped in try/except; `null` returned on failure without breaking other sections |
| PCR interpretation in risk score | Substring match against exact analytics.py strings — not raw PCR values — keeps semantics consistent if thresholds change |
| Static events schedule expiry | `SCHEDULE_VALID_UNTIL = 2027-03-31` triggers log WARNING 30 days before — update `_STATIC` in `events.py` by that date |

---

## Phase 22H — OAuth 2.0 + PKCE, multi-user isolation, security model

**Tools added:** 1 (1 net new tool; total 69) **Tests:** 1397 (41 files, 0 failures)

### What was built

**Multi-user isolation**
- `current_user` ContextVar set per request from Bearer token
- `_user_filter()` in journal/recommendation queries returns `1=0` when unauthenticated — users can never see each other's data
- DB schema v7: `user_id TEXT` column added to `trades` and `recommendation_log` tables; migration is idempotent

**Auth guard functions**
- `require_broker()` — raises PermissionError if no Bearer token; all personal data tools (portfolio, profile, orders, margins, positions) use this. Never use bare `get_broker()` for personal data.
- `_require_user()` — returns structured `{"status": "not_authenticated", "message": "call zerodha_login() first"}` for journal/recommendation tools; no exception raised.
- Unauthenticated clients get empty results or a clear message, never a server error.

**OAuth 2.0 + PKCE (MCP spec)**
- `/.well-known/oauth-protected-resource` and `/.well-known/oauth-authorization-server` — standard discovery endpoints
- `/oauth/authorize` — PKCE authorization endpoint; auto-completes if browser has `mcp_uid` cookie
- `/oauth/token` — token exchange endpoint
- `/oauth/register` — RFC 7591 dynamic client registration
- CORS headers on all OAuth endpoints
- `redirect_uri` HTTPS validation (localhost allowed for dev)
- Railway hostname added to `TransportSecuritySettings` to prevent 421 errors

**Browser login enhancements**
- `mcp_uid` cookie set on successful login (display only — not used for auth)
- Login page shows API key with blur + eye toggle + copy button
- Setup guide tabs: Claude Code, Claude Desktop, Cursor, Postman
- Shows "Welcome back, {uid}" if cookie present; "session already active" if broker authenticated

**Home page rewrite**
- MCP endpoint banner with one-click copy button
- Quick Start section with tabs for claude.ai, Claude Code, Claude Desktop, Cursor, Postman
- Actual commands/JSON configs generated client-side from `window.location.origin`
- Session card shows three states: fully authenticated (Bearer token), cookie-only (browser visitor), no session
- Security callout explaining free vs auth-required tools and that Bearer token stays server-side
- DB schema v7 and SSE endpoint shown in Server Info
- Tool count stays dynamic via `{tool_count}` placeholder

**Logout**
- `POST /logout` requires Bearer token; browser logout button prompts for API key
- `mcp_uid` cookie cleared on logout

**401 guard on /sse and /mcp**
- Both endpoints return `401 + WWW-Authenticate: Bearer resource_metadata=<well-known-url>` for any request without a valid Bearer token
- This is the MCP spec trigger for OAuth discovery — clients like claude.ai and Claude Desktop automatically open their OAuth flow when they see this response
- Authenticated requests (valid Bearer token present) pass through normally; the 401 is only for unauthenticated connections

**Guest token flow**
- `/oauth/authorize` page shows a "Continue as guest" button below the Zerodha credentials form
- Clicking it bypasses Zerodha login entirely — the server immediately issues an OAuth redirect with a freshly-minted Bearer token
- The token is stored in `api_key_store` with `user_id = "__guest__"`
- `uid == "__guest__"` is treated identically to `uid == None` throughout the codebase:
  - `require_broker()` → raises PermissionError (portfolio tools fail with auth error)
  - `_require_user()` → returns `{"status": "not_authenticated", "message": "..."}`
  - `_user_filter()` → returns `WHERE 1=0` (no journal data visible)
  - `check_auth_status()` → returns `{"authenticated": false}`
  - `zerodha_login()` → returns a login URL (same as for no-auth)
- All 50+ free tools (market data, options, technicals, dashboards, analysis, intelligence) work normally for guest tokens
- Personal tools (portfolio, journal, recommendations) reject guest with the same "not_authenticated" response as any unauthenticated call

### Key decisions

- Cookie is display-only: it lets the home page show a "connect your client" message to returning browser users, but auth always requires a Bearer header — never the cookie.
- `require_broker()` vs `_require_user()`: broker tools raise hard (portfolio calls fail visibly if unauthenticated); journal/recommendation tools return a soft "not_authenticated" dict so the agent can surface a clear message rather than an exception.
- OAuth PKCE chosen over simpler bearer-only to support claude.ai's automatic OAuth flow — no API key copy/paste needed for that client.
- Guest token uses `"__guest__"` as the user_id (not `None`) so it is a valid stored token; the equality check `uid == "__guest__"` gates it out of personal tools without needing a separate token type.
- 401 guard is on the transport endpoints, not on individual tool calls — tools never return 401. This keeps the MCP tool contract clean: tools return data or `{"error": "..."}` / `{"status": "not_authenticated"}`, never HTTP 401.

## Pre-Phase 4 Fixes — Calendar, Expiries, Dashboard Cleanup

**Tools added:** 1 (`get_sensex_dashboard`; total 64) **Tests:** 1584 (23 new/updated, 1 pre-existing sandbox-network failure unrelated to this work)

### What was built

**Monthly expiry calculation fixed (`src/market/calendar.py`)**
- SEBI's weekly-expiry rationalization (Nov 2024) left only NIFTY (NSE) and SENSEX (BSE) with a weekly series; BANKNIFTY, FINNIFTY, MIDCPNIFTY, and BANKEX are monthly-only now. `_nearest_expiry_algorithmic` previously treated all six as "nearest weekday", which produced weekly-style dates for indices that no longer have a weekly contract.
- Added `_last_weekday_of_month()` and `_nearest_monthly_expiry()`; `_MONTHLY_ONLY_INDICES = {banknifty, finnifty, midcap_nifty, bankex}` now route through the monthly calculation, rolling to next month once the current month's date has passed, then adjusting backward over holidays/weekends.
- Fixed `midcap_nifty`'s expiry weekday from Thursday to Monday in `_EXPIRY_WEEKDAY`.
- `get_market_calendar()` now also returns a `monthly_expiries` dict (last-weekday-of-month for all six indices, independent of weekly/monthly-only status) so NIFTY/SENSEX's monthly contract is visible alongside their weekly one.
- `nse_expiries`/`bse_expiries` descriptive blocks corrected to stop claiming a weekly series for indices that no longer have one.

**Sensex/Bankex live expiry — reused BSEOptionsService instead of INDmoney**
- The old `_live_expiries()` called a speculative `api.indstocks.com/option-chain-symbols` endpoint gated behind `INDSTOCKS_TOKEN` that doesn't exist in `INDmoneyBroker` (`get_option_chain` there is stubbed `"not_available"`) — so it never returned data.
- Replaced with `src.options.bse_service.get_bse_options_service().available_expiries()` — the same no-auth BSE API already powering `get_sensex_option_chain`/`get_bankex_option_chain`. `expiry_source_per_index.sensex/bankex` now genuinely reports `"live"` when the BSE API responds.
- Fixed a latent bug where a live expiry string that failed to parse left the index silently missing from `expiries` while still labeled `"live"` in `expiry_source_per_index`; it now falls back to `"algorithmic"` on parse failure. Added `"%d %b %Y"` (BSE's date format) to the parse attempts.

**BSE holiday static fallback (`src/calendar/fetcher.py`)**
- Added `resources/calendar/bse_{2025,2026,2027,2028}.json` static fallback files (mirroring the existing NSE calendars, per the documented "95%+ overlap" approximation) so `fetch_bse_holidays()` no longer depends entirely on a live scrape + NSE-derived proxy when both fail.
- Added `else` branches logging the HTTP status/body when NSE/BSE holiday endpoints respond with a non-200 status (previously only exceptions were logged; a clean non-200 response fell through silently).
- Confirmed `nse_holidays`/`bse_holidays` being `[]` for a given day is expected behavior when no holiday falls in the 30-day rolling window, not a data-loading bug — `resources/calendar/2026.json` already carries a full year of holidays.

**Dashboard cleanup — `signal`/`confidence`/`trade_setup`/`strategy` removed (`src/dashboard/service.py`)**
- `build_dashboard()`'s `_analysis_section` bypassed the Phase 22F tool-layer sanitization and exposed the raw `regime`/`confidence`/`signal` fields (deleted everywhere else in Phase 22F) plus full `trade_setup`/`strategy` blocks. Rewritten to reuse `src.tools.analysis._build_market_structure` — the same conversion the `detect_market_regime` tool uses — so the dashboard and that tool never disagree on what counts as a fact.
- `trade_setup` and `strategy` keys removed from the dashboard response entirely; `generate_trade_setup`/`recommend_strategy` are no longer called from the dashboard path. Use `create_trade_plan`/`build_option_strategy` for directional trade construction.
- `intelligence.risk_score.recommendation` dropped from the dashboard's slim risk-score view (the full `get_market_risk_score` tool is unaffected — its own `recommendation` field stays).
- `_build_summary` rewritten to be observation-only: price vs EMA20/EMA50, RSI value, MACD sign, ADX value + threshold note, PCR + interpretation, max pain, VIX level, and a factual high-impact-event note — no directional bias language, no "consider X" recommendation language.

**New tool — `get_sensex_dashboard`**
- `_options_section` now picks `BSEOptionsService` for `{SENSEX, BANKEX}` and the NSE `OptionsService` otherwise, so `build_dashboard("SENSEX")` works unmodified elsewhere (technicals/analysis were already symbol-generic via `src/market/symbols.py`).
- Registered in `src/tools/dashboard.py`, mirroring `get_nifty_dashboard`/`get_banknifty_dashboard`.

### Key decisions

- Monthly-vs-weekly routing lives in `_MONTHLY_ONLY_INDICES`, not a per-call flag, so every caller of `_nearest_expiry_algorithmic` (including tests) gets the correct behavior without remembering to opt in.
- BSE static holiday files mirror the NSE calendars rather than inventing unverified BSE-specific dates — consistent with the existing documented fallback design ("NSE holidays, 95%+ overlap"), just made durable against network failure instead of computed live every time.
- Dashboard cleanup expands Phase 22F's tool-layer-only boundary to include the dashboard aggregator: Phase 22F explicitly preserved internal consumers like the dashboard so downstream code wouldn't break, but the dashboard is itself a directly-callable MCP tool surface (not an internal-only consumer), so it now gets the same treatment as `detect_market_regime`.

## Phase 23 — Order Placement (Telegram bot + mobile web app)

**Tests:** 1984 passing + 6 skipped (42 new; the single Windows-only `test_env_manager.py::test_update_existing_and_preserve_spacing` `os.replace` PermissionError is a pre-existing sandbox artifact, unrelated to this work — passes on the Linux VM).

### What was built

First in-repo order *placement* (previously deferred to an unavailable external "Kite MCP"). Two surfaces share one core so the placement logic lives in exactly one place.

**Core — broker layer + execution package**
- `INDmoneyBroker.place_order(OrderRequest)` (`src/brokers/indmoney.py`) — first non-GET call in the file; `POST https://api.indstocks.com/order` with the same `Authorization` header as every read call. Contract from api-docs.indstocks.com/normal_orders/. Returns a uniform `{status, order_id, order_status, status_code, body}` dict; never raises. Success requires both HTTP 2xx AND body `status == "success"`.
- `OrderRequest` write-model + `to_indstocks_payload()` (`src/brokers/models.py`) — maps to native field names (`txn_type/security_id/limit_price/qty/segment/algo_id`), injects `algo_id` by exchange (`99999` NSE / `9999999999999999` BSE), omits `limit_price` for MARKET. The read-only `Order` dataclass is untouched (backward-compat).
- `place_order` is a new **abstract** method on `BrokerAdapter`; `ZerodhaBroker.place_order` is a concrete stub returning an error (no Kite subscription) so the class stays instantiable.
- `INDmoneyBroker.resolve_security_id(symbol, source)` — resolves trading symbol → INDstocks `security_id` via the existing `get_instruments()` CSV master (cached in-process). Orders key on `security_id`, not the symbol.
- `src/execution/service.py::submit_order(req, *, source, user_id, broker)` — the single entry point for both surfaces: places via the adapter, then best-effort logs to `zerodha.orders` (a logging failure never fails the order).
- `src/execution/repository.py::ExecutionRepository` — mirrors `MonitorRepository` (lazy ORM import, ISO-8601 timestamps, degrades to no-op when `DATABASE_URL` unset). New `zerodha.orders` table (`OrderLog` in `src/db/models.py`) + Alembic migration `0009_orders_table.py`, with `user_id` isolation and immutable requested-intent snapshot columns.

**A — Telegram command bot** (extends the existing `telegram_admin` bot — no new process)
- `/buy` and `/sell SYMBOL QTY [MARKET|LIMIT price] [product] [exchange]`, parsed by the pure `src/telegram_admin/order_parser.py` (unit-testable without Telegram). Symbol is resolved to `security_id` up front (bad symbol fails before the confirm prompt). Every order shows a YES/NO confirm keyboard (reuses the restart-confirm pattern) and only fires on `order_confirm:yes` — mirrors `cmd_restart_callback`.
- `/positions` and `/orders` read-only helpers. All handlers keep the existing `@admin_only` gate.

**B — Mobile web app** (`src/ui/trade.html` + routes in `src/server.py`)
- PIN-gated (`TRADE_PIN`), independent of the MCP OAuth/Bearer flow. `GET /trade` serves a phone-friendly form; `POST /trade/preview` validates + returns a confirm summary (no order); `POST /trade/place` is the only route that fires — so every order requires an explicit second request. Routes sit before the MCP fall-through and never touch `current_user`; `TRADE_PIN` (unset ⇒ feature disabled) is compared with `hmac.compare_digest`.
- `TRADE_PIN` added to `.env.example` and the admin bot's `ALLOWED_VARIABLES` (live-rotatable); `/show` masking extended to hide `*PIN*` vars.

### Key decisions

- **INDstocks native API over OpenAlgo.** OpenAlgo supports IndMoney but is a separate self-hosted server; native placement reuses the exact base URL + auth header `INDmoneyBroker` already speaks, adding zero infrastructure for a single-broker personal button.
- **One `submit_order` core, two surfaces.** Both the bot and the web app call it, so placement + logging never diverge.
- **MARKET passthrough.** INDstocks has no true MARKET order (it converts to LIMIT@live server-side); `order_type="MARKET"` is passed as-is and the confirm summaries state the live-price-LIMIT behavior.
- **Confirm-every-order on both surfaces** — the risk control for real-money placement, given the whole point is brokerage savings, not speed at the cost of fat-fingers.

### Follow-up — symbol search/autocomplete + web UI redesign (2026-07-11)

Typing exact INDstocks trading symbols blind (no feedback until submission) was the biggest usability gap in both surfaces. Added symbol discovery, reusing the same instrument master already used for `security_id` resolution:

- **`INDmoneyBroker.search_instruments(query, source, limit)`** (`src/brokers/indmoney.py`) — substring search over the cached instrument CSV; prefix matches (`RELIANCE` for query `REL`) rank before mid-string matches. Deliberately does **not** return `security_id` to callers — that's still resolved server-side at order time via `resolve_security_id`, so a client never needs to trust an id it fetched earlier.
- **Cache moved from instance-level to module-level** (`_instrument_cache` at module scope in `indmoney.py`, 6h TTL). `get_broker_adapter("indmoney")` constructs a fresh `INDmoneyBroker()` per call/request — an instance-level cache (the original design) would re-download the multi-MB instrument CSV on every autocomplete keystroke. Tests use an autouse fixture to clear the shared cache between tests.
- **`src/execution/service.py::search_symbols(query, segment=None)`** — the surface-agnostic entry point; without a segment hint it searches both `equity` and `fno` instrument masters so one search box covers stocks and options.
- **Web:** `GET /trade/symbols?q=...&pin=...` (PIN-gated like the other `/trade` routes) backs a live autocomplete dropdown in `trade.html` — debounced input, keyboard nav (↑/↓/Enter/Esc), picking a result also sets the exchange field. `trade.html` redesigned throughout: CSS custom properties for light/dark, card-based layout, BUY/SELL pill toggle, a real order-summary confirm screen (side badge, resolved instrument name, key/value grid) instead of raw HTML string concatenation.
- **Telegram:** new `/search TEXT` command (`search_command` in `handlers.py`) lists matching symbols with name + exchange so a user can look up the exact symbol before `/buy`/`/sell`, without leaving the chat. Added to `/start` help text as the first trading command.

15 new tests (`TestSearchInstruments`, `TestSearchSymbols`, `/trade/symbols` route tests, `/search` handler tests). Full suite: 2076 passed, 6 skipped.

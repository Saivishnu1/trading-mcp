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
├── journal/                 Trade Journal — SQLite-backed persistent log (Phase 12)
│   ├── db.py                Connection factory, schema init, reset_connection() test seam
│   └── service.py           log_trade, close_trade, get_open_trades, get_trade_history
├── recommendations/         Trade Recommendation Engine (Phase 13)
│   └── engine.py            recommend_trade, review_open_trades, get_daily_brief
├── tools/                   MCP tool registrations (one file per domain)
└── server.py                FastMCP server + ASGI app + /health endpoint
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
| `phase-14.6-consistency-hardening` | *(pending)* | Consistency & Data-Source Hardening — symbol unification, event-risk confidence gating, degradation flags, one confidence scale, common package, data_basis/staleness; 58 tools, 1011 tests |

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

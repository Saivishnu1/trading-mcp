# Zerodha Personal MCP — Development Log

**Repository:** `trading-mcp`
**Deployed:** Railway (`zerodha-mcp-production.up.railway.app`)
**Date:** 2026-06-17

---

## Project Overview

A personal Model Context Protocol (MCP) server that connects Claude to a Zerodha
trading account **without** requiring a paid Kite Connect subscription. Built across
eleven phases, from a bare authentication stub to a 48-tool trading intelligence platform
with market regime analysis, risk scoring, macro context awareness, portfolio intelligence,
and company-level catalyst tracking (news, earnings, event risk).

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

## Complete Tool Registry (48 tools)

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
| `phase-11b-catalyst-intelligence` | *(current)* | Catalyst Intelligence — news, earnings, event risk; 48 tools, 551 tests |

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

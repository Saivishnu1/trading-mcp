# PROJECT_STATE.md

## Project

Name: Zerodha Personal MCP

Repository: trading-mcp

Deployment:

* Railway
* Streamable HTTP: /mcp
* SSE: /sse

Status:

* Active Development

---

## Current State

Current Phase: 15A (complete)

Latest Tag:
phase-15a-journal-analytics

Tool Count:
59

Test Count:
1030 (29 test files, 0 failures)

Deployment Status:
Production deployed on Railway

---

## Completed Phases

✅ Phase 0 — Base Server

✅ Phase 1 — Options Analytics

✅ Phase 2 — Technical Indicators

✅ Phase 3 — Analysis Engine

✅ Phase 4 — Dashboard

✅ Phase 4.1 — Strategy Alignment

✅ Phase 5 — Trade Planner

✅ Phase 5.1 — Trade Quality Filter

✅ Phase 5.2 — Risk/Reward Optimization

✅ Phase 6 — Option Strategy Builder

✅ Phase 7 — Trade Review Engine

✅ Phase 8 — Equity Option Chain Support

✅ Phase 9 — Automated Testing

✅ Phase 10 — Market Intelligence Engine

✅ Phase 11A — Portfolio Intelligence

✅ Phase 11B — Catalyst Intelligence (News, Earnings & Event Risk)

✅ Phase 12 — Trade Journal Foundation

✅ Phase 13 — Trade Recommendation Engine

✅ Phase 14 — Position Sizing Engine

✅ Phase 14.5 — Reliability Hardening

✅ Phase 14.6 — Consistency & Data-Source Hardening

✅ Phase 15A — Journal Performance Analytics

⬜ Phase 15B — next

---

## Current Tool Registry

Authentication: 2

Account & Portfolio: 4

Market Data: 7

Options & Derivatives: 8

Technicals: 6

Analysis: 5

Dashboard: 2

Trade Planner: 1

Option Strategy Builder: 1

Trade Review: 1

Market Intelligence: 4

Portfolio Intelligence: 3

Catalyst Intelligence: 4

Trade Journal: 5

Trade Recommendations: 3

Position Sizing: 3

Total: 59

---

## Recent Changes

Phase 15A:

* 1 new tool: get_performance_analytics (58 → 59); 19 new tests → 1030
* Realized-outcome feedback loop over CLOSED journal trades — answers "does the model have edge?"
* Buckets closed trades by signal, regime, and entry-confidence band (from analysis_snapshot.confidence); per bucket: trades, wins, win_rate_pct, avg_pnl, total_pnl, low_sample
* overall adds profit_factor (gains/|losses|; null when no losses — JSON-safe)
* notes surface confidence-calibration check (does high band win more than low?) and small-sample warnings
* Buckets below min_sample (default 10) flagged low_sample so a thin journal can't be over-read
* Read-only; reuses existing journal schema; no persistent recommendation storage added
* Tagged: phase-15a-journal-analytics

Phase 14.6:

* No new tools (58 total, unchanged); 144 new tests → 1011
* New src/market/symbols.py — single source of truth for symbol resolution; removed 3 divergent _INDEX_YF tables (fixed get_quote vs indicator alias mismatch)
* New src/common/ package: scoring.py (risk_rating, apply_size_factors), signals.py (signal sets, direction_from_signal) — removed duplicated rating bands and size-factor math
* recommend_trade reads event_risk.confidence — no longer hard-gates AVOID on low-confidence (fabricated) event-risk scores; gating_data_available.event_risk reflects it
* get_market_risk_score reports confidence/is_degraded/degraded_components — all-fallback scores no longer masquerade as reliable
* One confidence scale (0–85) everywhere via _scale_confidence (rescaled, not clamped); removed dead min(100,...) in reviewer
* PCR risk scoring keys on stable pcr_sentiment_code, not display prose
* recommend_trade + plan surface data_basis (source/last_candle_date/staleness_days); staleness caution > 5 days
* _analyze_technicals cached 60s per (symbol, lookback) — one fetch per flow, no mid-call divergence; clear_analysis_cache() seam
* Near-boundary cautions (RSI ~30/70, event risk ~80); scoring property/shape tests added
* get_historical documents auto_adjust (adjusted price basis)
* Tagged: phase-14.6-consistency-hardening

Phase 14.5:

* No new tools (58 total, unchanged)
* Fix 1 (service.py): NaN rows from yfinance filtered in get_historical() — eliminates entire NaN propagation chain
* Fix 2 (regime.py): _is_invalid() replaces None in (...) guard — catches float NaN which bypasses None membership tests
* Fix 3 (tools/technicals.py): analyze_technicals returns error on any NaN indicator
* Fix 4 (regime.py): RSI > 70 → bearish +10 (overbought); RSI < 30 → bullish +10 (oversold); 30–70 range unchanged
* Fix 5 (regime.py): Confidence capped at 85 — no indicator model warrants 100%
* Fix 6 (engine.py): Event risk and VIX gating failures surface as cautions; gating_data_available field added
* Fix 7 (tools/technicals.py): Docstrings clarify lookback period differences
* 15 new tests; RH-1 through RH-3 regression guards
* Tagged: phase-14.5-reliability-hardening

Phase 14:

* 3 new tools: size_equity_trade, size_options_trade, size_from_recommendation
* New src/sizer/ package: engine.py (all logic), src/tools/sizer.py (MCP registration)
* size_equity_trade: quantity = max(1, floor(risk_budget / stoploss_distance)); direction-aware for LONG/SHORT
* size_options_trade: lots = max(1, floor(risk_budget / (premium_distance × lot_size))); caution when capital_at_risk > 5%
* size_from_recommendation: calls recommend_trade() → uses its position_size as base; applies ONLY portfolio heat on top (Phase 13 factors already applied)
* Portfolio heat: sum of open trade risks from journal / capital; stoploss-absent trades use 2% default
* Heat ELEVATED (≥7%) → size ×0.75; CRITICAL (≥9%) → size ×0.50; stacks with portfolio risk report score
* Portfolio risk HIGH (≥75) → ×0.75; EXTREME (≥90) → ×0.50; broker auth failure → factor silently skipped
* All factors stack multiplicatively via _apply_size_factors; floor at 1
* size_from_recommendation returns AVOID with null sizing fields and null log_trade_params (no accidental logging)
* log_trade_params returned by all 3 tools; keys validated against log_trade() signature
* Journal schema v1 → v2: adds risk_amount REAL, capital_at_risk REAL, portfolio_heat_at_entry REAL
* Migration via ALTER TABLE ADD COLUMN; idempotent try/except per statement; version stamp updated
* Immutability rule: risk_amount, capital_at_risk, portfolio_heat_at_entry set at entry, never modified
* log_trade() gains 3 new optional params (risk_amount, capital_at_risk, portfolio_heat_at_entry); all callers unaffected
* 107 new tests across 2 files; PS-1 through PS-5 regression guards
* Schema version tests in test_journal_db.py updated to reference _SCHEMA_VERSION constant (not hardcoded 1)
* Zero changes to existing 55 tools; no regressions
* Tagged: phase-14-position-sizing

Phase 13:

* 3 new tools: recommend_trade, review_open_trades, get_daily_brief
* New src/recommendations/ package: engine.py (all logic), src/tools/recommendations.py (MCP registration)
* recommend_trade: portfolio-aware ENTER/WAIT/AVOID; reuses create_trade_plan, get_event_risk, get_india_vix, get_open_trades
* Event risk ≥80 → trade_allowed=False (AVOID); 60–79 → size ×0.70 + caution (WAIT)
* VIX EXTREME → trade_allowed=False; HIGH → caution only
* Duplicate exposure (same symbol+direction already open) → size ×0.50 + WAIT
* Size factors stack multiplicatively; floor at 1
* review_open_trades: per-position HOLD/REDUCE/EXIT via review_trade; stoploss_breached, target_reached, current_pnl, summary
* get_daily_brief: morning briefing; market_context (VIX, risk score, global pulse, upcoming events); alerts for EXIT/stoploss/HIGH events
* All market_context sub-calls isolated in try/except — no partial failure surfaces as error
* All imports use module-alias pattern for monkeypatch compatibility across module boundaries
* get_daily_brief calls review_open_trades() as local name → patchable via rec_engine attribute
* 84 new tests across 2 files; RR-1 through RR-5 regression guards
* Zero changes to existing 52 tools or any existing test file
* Tagged: phase-13-trade-recommendation

Phase 12:

* 4 new tools: log_trade, close_trade, get_open_trades, get_trade_history
* New src/journal/ package: db.py (connection factory, schema), service.py (CRUD + P&L)
* SQLite storage via JOURNAL_DB env var (default: journal.db); no external services
* Schema v1: 30 columns including trade_type (EQUITY default), created_by (MANUAL default), analysis_snapshot (JSON)
* Trade IDs: TRD-xxxxxxxx (8 hex chars from uuid4) — short enough to copy, unique for personal use
* P&L calculation: (exit-entry)*qty for LONG, (entry-exit)*qty for SHORT; pnl_percent relative to entry
* risk_reward auto-calculated from stoploss + target if not provided explicitly
* Tags and analysis_snapshot stored as JSON, returned as Python objects
* WAL mode + threading.Lock for safe concurrent writes; check_same_thread=False
* Error isolation: all service functions return {"error": "..."} — no exceptions propagate to MCP
* Testability: reset_connection() seam allows in-memory SQLite injection per test
* 110 new tests across 3 files; JR-1 through JR-5 regression guards
* No changes to existing 48 tools or any existing test file
* Tagged: phase-12-trade-journal

Phase 11B:

* 4 new tools: get_symbol_news, get_news_sentiment, get_earnings_calendar, get_event_risk
* New src/catalyst/ package: constants.py, news.py, earnings.py, event_risk.py
* Symbol resolution: _to_yf_ticker() handles bare/prefixed/suffixed/index aliases — idempotent
* Keyword-based sentiment: no ML, no API key — _POSITIVE/_NEGATIVE keyword sets in constants.py
* Earnings proximity: 5-tier scoring (IMMINENT/VERY_HIGH/HIGH/MEDIUM/LOW) with 0-100 score
* Event risk composite: earnings 40% + news 30% + market risk 30% (reuses Phase 10)
* Confidence model: 1.0 (all sources) / 0.8 (2 sources) / 0.5 (market only) / 0.3 (none)
* Dual catalyst fields: nearest_catalyst (by date) + highest_impact_catalyst (by priority)
* Catalyst priority: EARNINGS=100, SPLIT=70, DIVIDEND=40
* Error isolation: property-access exceptions surface as "error" key; no propagation
* Cache TTL: news 1800s, earnings 3600s, event_risk 300s (all thread-safe)
* 124 new tests across 4 files; ER-1 through ER-5 regression guards
* No changes to existing 44 tools or any existing test file
* Tagged: phase-11b-catalyst-intelligence

Phase 11A:

* 3 new tools: get_portfolio_risk_report, get_portfolio_regime_analysis, get_portfolio_exposure_breakdown
* New src/portfolio_intelligence/ package: service.py
* Reuses review_trade, get_market_risk_score — no duplicated logic
* Per-position analysis: risk_score, regime, review_action, thesis_status
* Portfolio aggregation: value-weighted risk score, HHI diversification, concentration risk
* Dashboard-style error isolation: broker failure → error dict; per-symbol failure → nulls, others continue
* Symbol deduplication: holdings take priority over net positions for same symbol
* 66 new tests across 2 files; PR-1 through PR-5 regression guards
* Coverage: portfolio_intelligence/service.py 97%
* Tagged: phase-11a-portfolio-intelligence

Phase 10:

* 4 new tools: get_india_vix, get_global_pulse, get_upcoming_events, get_market_risk_score
* New src/intelligence/ package: vix.py, global_pulse.py, events.py, risk.py
* Dashboard now includes isolated intelligence section (VIX, global sentiment, events, risk score)
* _build_summary appends event-warning when HIGH-impact event within 3 days
* create_trade_plan exposes risk_score (visibility only — no logic change)
* 91 new tests across 5 files; IR-1 through IR-5 regression guards
* Coverage: events 97%, vix 98%, global_pulse 91%, risk 92%
* Static events schedule covers RBI MPC, FOMC, India CPI/GDP, US NFP through 2027-03-31
* Tagged: phase-10-market-intelligence

Phase 9:

* 270 tests across 9 files — 0 failures
* Coverage: analysis 88%, strategy 92%, planner 86%, review 84%, dashboard 85%, indicators 92%, options analytics 100%
* 7 named regression guards protecting historical bugs
* pytest + pytest-cov added to dev deps; pythonpath configured
* Tagged: phase-9-automated-testing

---

## Current Open Work

None. Phase 14.6 complete and tagged.

---

## Known Constraints

* No Kite Connect subscription
* Uses Zerodha web session
* NSE data via jugaad-data
* Pure Python indicators
* No TA-Lib
* No NumPy dependency
* Railway deployment target
* Events calendar requires manual update when approaching 2027-03-31

---

## Important Compatibility Rules

Never remove:

generate_trade_setup:

* entry
* stoploss
* target

Keep alongside:

* entry_above
* entry_below
* bull_target
* bear_target

recommend_strategy:

* strategy
* recommended

Both must remain available.

Dashboard response keys added in Phase 10 (`intelligence`) are additive — existing
consumers that don't read it are unaffected.

create_trade_plan `risk_score` key is additive — never remove, never use it to gate
`trade_allowed`.

---

## Technical Debt (priority order)

1. market/service.py at 36% coverage — get_historical NaN path now tested; live-quote (NSELive/yfinance) and jugaad paths still untested
2. options/service.py at 60% coverage — jugaad fallback path untested
3. `regime` variable assigned but unused in dashboard `_build_summary`
4. TTL cache boilerplate duplicated across 6 modules (vix/global/events/risk/event_risk + analysis cache) — candidate for src/common/cache.py
5. Options chain fetching duplicated in 3 places (dashboard, planner, risk)
6. events.py: schedule expiry should surface as a response key, not just a log warning
7. live quote (get_quote) vs analysis basis (get_historical, adjusted) are different vendors/levels — entry/stop/target are in adjusted space; consider reconciling or labelling at the tool boundary (Phase 14.6 added data_basis as a first step)

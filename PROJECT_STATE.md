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

Current Phase: 11B (complete)

Latest Tag:
phase-11b-catalyst-intelligence

Tool Count:
48

Test Count:
551 (19 test files, 0 failures)

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

⬜ Phase 12 — next

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

Total: 48

---

## Recent Changes

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

None. Phase 11B complete and tagged.

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

1. market/service.py at 33% coverage — data transformation path untested
2. options/service.py at 60% coverage — jugaad fallback path untested
3. `regime` variable assigned but unused in dashboard `_build_summary`
4. TTL cache boilerplate duplicated across 5 modules — candidate for src/utils/cache.py
5. Options chain fetching duplicated in 3 places (dashboard, planner, risk)
6. events.py: schedule expiry should surface as a response key, not just a log warning
7. tools/technicals.py at 22% — `_load_closes` symbol mapping untested

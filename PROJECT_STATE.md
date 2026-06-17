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

Current Phase: 10 (next)

Latest Tag:
phase-9-automated-testing

Tool Count:
37

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

⬜ Phase 10 - Reliability & Observability

⬜ Phase 11 - Production Features

⬜ Phase 12 - Deployment Hardening & Release

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

Total: 37

---

## Recent Changes

Phase 9:

* 270 tests across 9 files — 0 failures
* Coverage: analysis 88%, strategy 92%, planner 86%, review 84%, dashboard 85%, indicators 92%, options analytics 100%
* 7 named regression guards protecting historical bugs
* pytest + pytest-cov added to dev deps; pythonpath configured
* Scratch scripts (test_jugaad*, test_phase8*) deleted; .coverage gitignored
* Tagged: phase-9-automated-testing

Phase 8:

* Added get_equity_option_chain
* Fixed NSE:RELIANCE prefix bug
* Equity option chains now return real strikes and premiums
* build_option_strategy works for NSE equities

---

## Current Open Work

Phase 10 — Reliability & Observability (not started)

---

## Known Constraints

* No Kite Connect subscription
* Uses Zerodha web session
* NSE data via jugaad-data
* Pure Python indicators
* No TA-Lib
* No NumPy dependency
* Railway deployment target

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

---

## Next Immediate Task

Phase 10 — Reliability & Observability.

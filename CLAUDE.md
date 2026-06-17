# CLAUDE.md

## Project

Zerodha Personal MCP

Current Phase: 10 (complete) — Phase 11 next

Current Tool Count: 41

Primary Goal:
Build a personal trading intelligence MCP server with reusable analysis, planning, strategy, review, and dashboard capabilities.

---

## Architecture Rules

* Reuse existing functions whenever possible.
* Do not duplicate indicator calculations.
* Do not duplicate option analytics.
* Prefer composition over new implementations.
* Existing modules are the source of truth.

Reuse chain:

generate_trade_setup
→ recommend_strategy
→ create_trade_plan
→ build_option_strategy
→ review_trade
→ dashboard

---

## Backward Compatibility

Never remove existing response fields unless explicitly requested.

Maintain compatibility for:

generate_trade_setup:

* entry
* stoploss
* target

alongside:

* entry_above
* entry_below
* bull_target
* bear_target

Preserve existing dashboard consumers.

---

## Development Workflow

Before implementing:

1. Inspect existing code.
2. Reuse existing logic.
3. Identify downstream consumers.
4. Check schema compatibility.

After implementing:

1. Run validation.
2. Check backward compatibility.
3. Update DEVELOPMENT.md.
4. Suggest commit message.

---

## Token Efficiency Rules

Do NOT re-read DEVELOPMENT.md unless requested.

Assume previous phases are complete.

When continuing work:

* Use current phase information.
* Focus only on changed files.
* Avoid re-explaining completed phases.

When validating:

* Validate only affected modules first.
* Avoid full-project validation unless requested.

When generating tests:

* Match implementation exactly.
* Inspect code before writing assertions.
* Phase 9 is complete — do NOT regenerate existing test files.
* Run `uv run pytest tests/ -v` to validate; never skip it.

---

## Current Known Constraints

* No Kite Connect subscription.
* NSE data via jugaad-data + fallback.
* Pure Python indicators.
* No TA-Lib.
* No NumPy requirement.
* Railway deployment.
* 361 unit + regression tests across 13 test files (pytest, no live network calls).
* Coverage: analysis 90%, strategy 92%, planner 89%, review 84%, dashboard 89%, intelligence 91–98%.

---

## Git Workflow

After completing a phase:

1. Validate.
2. Generate commit message.
3. Generate tag suggestion.
4. Wait for approval before pushing.

---

## Output Style

Prefer:

* concise summaries
* change impact analysis
* compatibility checks

Avoid:

* repeating project history
* restating completed phases
* unnecessary architecture explanations

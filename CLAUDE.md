# CLAUDE.md

## Project

Zerodha Personal MCP

Current Phase: Phase 3 — Chart Awareness Engine (analyze_chart)

Current Tool Count: 68

Primary Goal:
Build a personal trading intelligence MCP server with reusable analysis, planning, strategy, review, and dashboard capabilities.

---

## Orchestration

This MCP is one of three in the trading intelligence stack:

1. zerodha-trading-intelligence (this MCP) — intelligence layer
2. Indmoney MCP — wealth and stock data layer
3. Kite MCP — order execution layer (unavailable, fix pending)

Always call get_capabilities() first to get routing rules.
Use get_market_awareness() as primary composite tool.
Do not duplicate calls handled better by companion MCPs.

Tool count: 68

Manifest lives in `src/orchestration/manifest.py` (`MCP_MANIFEST`). `get_capabilities()` and
`get_tool_health()` in `src/tools/meta_tools.py` both read from it — update the manifest, not
the tool bodies, when routing rules or companion MCP status change.

---

## Architecture Rules

* Reuse existing functions whenever possible.
* Do not duplicate indicator calculations.
* Do not duplicate option analytics.
* Prefer composition over new implementations.
* Existing modules are the source of truth.

Reuse chain:

create_trade_plan
→ build_option_strategy
→ review_trade
→ dashboard

---

## Backward Compatibility

Never remove existing response fields unless explicitly requested.

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

* `zerodha_login()` takes NO parameters — returns `{authenticated, login_url}`. Never add credential params back.
* Login page at `/login` (HTML form) and `/auth/status` (JSON) are ASGI routes in `server.py`, not MCP tools.
* `ui/login.html` is the template; loaded at runtime via `_LOGIN_TEMPLATE`. Edit the file, not the server string.
* No Kite Connect subscription.
* NSE data via jugaad-data + fallback.
* Pure Python indicators.
* No TA-Lib.
* No NumPy requirement.
* Railway deployment.
* 1924 unit + regression tests across 62 test files (pytest, no live network calls) as of 2026-07-10.
* Coverage: analysis 92%, strategy 92%, planner 89%, review 84%, dashboard 89%, intelligence 92–98%, portfolio_intelligence 97%, catalyst 90%+, journal 97%, recommendations 98%, sizer 95%, common 100%.
* Confidence is one 0–85 scale system-wide (regime + setup), via regime._scale_confidence — rescaled into the band, not clamped. Never reintroduce a 0–100 confidence.
* Symbol resolution has ONE home: src/market/symbols.py (to_yf / is_nse_stock / is_index / INDEX_YF / normalize_symbol). Do not add per-module alias tables.
* Shared scoring/signals live in src/common/ (risk_rating, apply_size_factors, signal sets). Reuse them; do not duplicate.
* Risk/event scores carry confidence/is_degraded — never gate hard on a degraded or low-confidence composite without surfacing a caution.
* Analysis basis is yfinance EOD adjusted candles (see data_basis); live quotes (NSELive) are a different vendor/level.
* `risk_amount`, `capital_at_risk`, `portfolio_heat_at_entry` are schema v2 immutable entry-time snapshots — never recalculate or modify after trade creation.
* All MCP tool responses are wrapped: `{"data": <output>, "meta": <trust context>}` — see src/meta.py. Tests that call tool wrappers directly must use `result["data"]`, not `result` directly.
* Journal DB is schema v7. `user_id` column in `trades` and `recommendation_log` tables. Multi-user isolation via `current_user` ContextVar + `_user_filter()`. Partition constants in src/recommendation_log/service.py — NEVER flip bootstrap_period/bias_contaminated automatically; only on conscious human decision.
* `confidence`, `signal`, `trade_quality`, `quality`, `bullish_probability` are DELETED (Phase 22F). Do not add them back.
* `detect_market_regime` returns `market_structure` (boolean facts + descriptor array), not `regime`/`confidence`. The `regime` key is deleted.
* `generate_trade_setup` (internal service function, not an MCP tool) returns `entry/stoploss/target/entry_above/entry_below/bull_target/bear_target/reasoning/market_structure`. `reasoning` is observation-only — no predictive language.
* DB schema v5 in meta layer (`meta["schema_version"] == 5`). Journal DB is schema v7 (user_id isolation).
* `require_broker()` must be used for all personal Zerodha data tools (portfolio, profile, orders, positions, margins). `_require_user()` for journal/recommendation tools. NEVER use `get_broker()` directly for personal data access — it bypasses the auth check.
* OAuth 2.0 + PKCE endpoints: `/oauth/authorize`, `/oauth/token`, `/oauth/register`. Well-known metadata at `/.well-known/oauth-protected-resource` and `/.well-known/oauth-authorization-server`.
* `mcp_uid` cookie is for browser display only — set on login, cleared on logout. It is NOT an auth token. Auth is always via Bearer token in HTTP header.
* `check_auth_status()` and `zerodha_login()` are scoped to caller's Bearer token, not global. Unauthenticated requests get empty results or a clear "call zerodha_login() first" message — never a 401 error from tool calls.
* **Guest token (Phase 22H):** `uid == "__guest__"` is treated identically to `None` in `require_broker()`, `_require_user()`, `check_auth_status()`, and `zerodha_login()`. Guest users get `authenticated: false` and "not_authenticated" from personal tools. Never grant guest access to portfolio, journal, or recommendation tools.
* **401 guard on `/sse` (GET) and `/mcp`:** Both endpoints return `401 + WWW-Authenticate: Bearer resource_metadata=...` for unauthenticated connections. This triggers OAuth discovery in MCP clients (claude.ai, Claude Desktop) automatically. Do not remove this guard.
* **OAuth authorize page (`/oauth/authorize`)** shows the Zerodha login form AND a "Continue as guest" button. Guest click → instant OAuth redirect → guest Bearer token mapped to `user_id = "__guest__"` in api_key_store. Full login → real Bearer token (`sess_xxx`) mapped to the owner's Zerodha user_id. Both flows issue standard OAuth tokens; the difference is only the user_id stored server-side.
* **Wall-break alerts are hold-confirmed, not touch-triggered (2026-07-10).** `oi_call_wall_break`/`oi_put_wall_break` only reach Telegram after `wall_break_confirm_candles` (default 3) consecutive polls beyond the wall — see `MarketIntelligence.check_oi_walls` and `monitor.session_state.call_wall_break_streak`/`put_wall_break_streak`. A touch that reverts before confirmation fires `oi_wall_rejection` instead. The raw single-poll touch is still logged (`delivered=False`) for backtesting, never pushed to Telegram.
* **Indicator source is Zerodha-first, not yfinance-first (2026-07-10).** `src/tools/technicals.py::_load_candles_with_source`/`_load_closes_with_source` try the tiered chart_awareness fetcher (Zerodha → INDmoney → yfinance) before falling back to the yfinance-only market service. `calculate_atr` and the dashboard's technicals section (`_technicals_section`) both surface which source actually served the candles via a `data_source`/`source` field — never hardcode `"yfinance"` in new indicator meta builders.
* **Max-pain pinning risk is surfaced proactively (2026-07-10).** `src/options/analytics.py::check_pinning_risk` is the single source of truth — used by `market_awareness/engine.py` (`calendar.pinning_risk`), `dashboard/service.py` (`options.pinning_risk`), and the monitor's intraday `check_pinning_risk` alert (type `pinning_risk`, cooldown `cooldown_pinning`). Do not duplicate the threshold logic.
* **`get_trade_cost_estimate` (2026-07-10)** is a directional brokerage/STT estimate, not a ledger reconciliation — reuses `require_broker().orders()`, never touches the `Trade` model's immutable snapshot fields.

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

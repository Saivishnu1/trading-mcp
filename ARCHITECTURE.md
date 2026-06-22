## Production MCP Chain

Market Service
    ↓
Technicals
    ↓
Analysis
    ↓
Dashboard
    ↓
Planner
    ↓
Strategy Builder
    ↓
Review Engine

---

## Research Infrastructure (scripts/)

Walk-forward audit framework for evaluating regime model changes before
they reach production. Not part of the MCP server — runs offline against
pre-downloaded OHLCV data.

```
scripts/
└── regime_audit.py   Walk-forward regime predictiveness audit
                      Uses: src/analysis/regime._classify_regime()
                            src/technical/indicators.*
                            src/market/service.get_historical()
```

**Phase 20A finding:** EMA20/EMA50 + ADX regime engine failed directional
predictiveness audit on NSE equities (2022-2025). Run new regime models
through this framework before wiring them into the recommendation chain.

---

## Auth Architecture (Phase 22H)

```
HTTP request to /sse or /mcp
    │
    ├── No Bearer token → 401 + WWW-Authenticate: Bearer resource_metadata=...
    │       MCP clients (claude.ai, Claude Desktop) auto-trigger OAuth discovery
    │
    └── Bearer token present → resolve uid from api_key_store
            │
            ├── uid == "__guest__"  → current_user = None (guest)
            │       require_broker() raises PermissionError
            │       _require_user()  returns {"status":"not_authenticated"}
            │       _user_filter()   returns "1=0" → empty DB results
            │       check_auth_status() → authenticated: false
            │       50+ free market data / options / technicals tools work normally
            │
            ├── uid == real user_id → current_user = uid (full login)
            │       require_broker() passes → personal tools work
            │       _user_filter() returns "user_id = ?" → journal isolated
            │       All 69 tools available
            │
            └── uid == None (no token) → same behavior as "__guest__"

OAuth flow (MCP clients: claude.ai / Claude Desktop)
    │
    ├── /.well-known/oauth-authorization-server  (discovery)
    ├── /.well-known/oauth-protected-resource    (discovery)
    ├── /oauth/register   (RFC 7591 dynamic client registration)
    ├── /oauth/authorize  (PKCE login page)
    │       ├── Zerodha credentials form → full login → sess_xxx token → real uid stored
    │       └── "Continue as guest" button → instant redirect → guest token → uid = "__guest__"
    └── /oauth/token      (token exchange → Bearer token issued)
```

### Guest token

- Created when user clicks "Continue as guest" on `/oauth/authorize`
- `user_id = "__guest__"` stored in `api_key_store` for the issued token
- `uid == "__guest__"` is treated identically to `None` in all auth guards
- Gives access to all free tools (50+): market data, options, technicals, dashboards, analysis, intelligence
- Personal tools (`require_broker()`, `_require_user()`) reject guest with "not_authenticated" — identical to no-auth behavior
- `check_auth_status()` returns `authenticated: false` for guest tokens

### Auth guard functions

| Guard | Used by | Behavior for guest or no-auth |
|-------|---------|-------------------------------|
| `require_broker()` | Portfolio, profile, orders, margins, positions | Raises `PermissionError` → MCP error response |
| `_require_user()` | Journal, recommendation tools | Returns `{"status": "not_authenticated", "message": "..."}` |
| `_user_filter()` | All DB queries | Returns `WHERE 1=0` clause → zero rows |

### Cookie vs Bearer

- `mcp_uid` cookie: browser display only. Set on login, cleared on logout. Shows user info on home page.
- Bearer token: actual auth credential. Sent in `Authorization` header. Never visible in chat or tool args. Never stored client-side in a cookie.

---

## Key src/ Modules

```
src/
├── broker/               Zerodha session (zerodha_web + jugaad fallback); require_broker()
├── market/               yfinance OHLCV + quote service; symbols.py (single symbol resolver)
├── options/              NSE option chain (jugaad NSELive) + analytics
├── technical/            Pure-Python indicators: RSI, EMA, MACD, ADX, ATR
├── analysis/             Regime detection, trade setup, strategy recommendation
├── planner/              Trade plan composition
├── strategy/             Option strategy builder
├── review/               Trade reviewer (HOLD/REDUCE/EXIT)
├── dashboard/            Aggregator
├── intelligence/         VIX, global pulse, events, market risk score
├── portfolio_intelligence/ Portfolio risk, regime distribution, exposure
├── catalyst/             News, earnings, event risk
├── journal/              Trade journal (Turso cloud SQLite); schema v7 + user_id isolation
├── recommendation_log/   Decision quality logger; _require_user() + _user_filter()
├── recommendations/      recommend_trade, review_open_trades, get_daily_brief
├── feedback/             Calibration adjustment (Phase 18)
├── calibration/          Brier score, reliability curve (Phase 17)
├── sizer/                Position sizing engine (Phase 14)
├── common/               Shared scoring, signals, risk rating
├── tools/                MCP tool registrations (one file per domain)
└── ui/                   Static HTML templates (home.html, login.html)
```
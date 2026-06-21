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
HTTP request
    │
    ├── Bearer token present?
    │       │
    │       ├── Yes → set current_user ContextVar → broker scoped to that user
    │       │          require_broker() passes → personal tools work
    │       │          _user_filter() returns "user_id = ?" → journal isolated
    │       │
    │       └── No  → current_user = None
    │                  require_broker() raises PermissionError
    │                  _user_filter() returns "1=0" → empty results
    │                  _require_user() returns {"status":"not_authenticated"}
    │
    └── OAuth flow (claude.ai / Claude Desktop)
            │
            ├── /.well-known/oauth-authorization-server  (discovery)
            ├── /.well-known/oauth-protected-resource    (discovery)
            ├── /oauth/register   (RFC 7591 dynamic client registration)
            ├── /oauth/authorize  (PKCE; auto-complete if mcp_uid cookie set)
            └── /oauth/token      (token exchange → Bearer token issued)
```

### Auth guard functions

| Guard | Used by | Behavior when unauthenticated |
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
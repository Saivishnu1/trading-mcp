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

## Key src/ Modules

```
src/
├── broker/               Zerodha session (zerodha_web + jugaad fallback)
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
├── journal/              Trade journal (Turso cloud SQLite)
├── recommendations/      recommend_trade, review_open_trades, get_daily_brief
├── feedback/             Calibration adjustment (Phase 18)
├── calibration/          Brier score, reliability curve (Phase 17)
├── sizer/                Position sizing engine (Phase 14)
├── common/               Shared scoring, signals, risk rating
└── tools/                MCP tool registrations (one file per domain)
```
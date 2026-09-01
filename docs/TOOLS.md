# Tool reference

78 MCP tools, generated from the live docstrings in [`src/tools/`](../src/tools/). Every tool's
response is wrapped in the trust metadata envelope described in the root
[README](../README.md#tool-response-format).

### Authentication (4)

| Tool | Description |
|---|---|
| `zerodha_login()` | Check authentication status and return a browser login URL if not authenticated. |
| `get_profile()` | Return the authenticated Zerodha user's profile. |
| `check_auth_status()` | Check whether this client has an active Zerodha session. |
| `zerodha_logout()` | Log out the current user — clears their session and invalidates the API key. |

### Portfolio (4)

| Tool | Description |
|---|---|
| `get_holdings()` | Return your long-term demat holdings. |
| `get_positions()` | Return your current intraday and carry-forward positions. |
| `get_margins()` | Return available fund margins for a segment. |
| `analyze_portfolio()` | Returns unified portfolio analytics across brokers. |

### Multi-broker — Zerodha + INDmoney (8)

| Tool | Description |
|---|---|
| `get_unified_holdings()` | Returns combined F&O and equity holdings from Zerodha + INDmoney. |
| `get_unified_positions()` | Returns open derivative positions from Zerodha + INDmoney. |
| `get_unified_funds()` | Returns available funds from zerodha, indmoney, or both brokers combined. |
| `get_unified_orders()` | Returns today's orders from zerodha, indmoney, or both brokers combined. |
| `get_broker_status()` | Returns authentication status for each configured broker (zerodha, indmoney). |
| `get_all_open_positions()` | Unified open-position view across Zerodha + INDmoney, all segments. |
| `get_indmoney_trades()` | Returns past executed trades from INDmoney (today's filled trades). |
| `get_indmoney_raw_data()` | Diagnostic tool — returns the unmodified INDstocks API response for a given data kind. |

### Market data (4)

| Tool | Description |
|---|---|
| `get_quote()` | Return a full market quote for one or more instruments. |
| `get_ltp()` | Return just the last traded price for instruments — fastest quote call. |
| `get_historical_data()` | Return historical OHLCV candle data via Yahoo Finance. |
| `get_intraday_snapshot()` | Current intraday OHLC snapshot with range metrics. |

### Instruments (1)

| Tool | Description |
|---|---|
| `search_instruments()` | Search instruments by trading symbol or company name. |

### Options & derivatives (9)

| Tool | Description |
|---|---|
| `get_expiries()` | List the available option expiry dates for an index. |
| `get_nifty_option_chain()` | Fetch the NIFTY 50 index option chain from NSE. |
| `get_banknifty_option_chain()` | Fetch the BANK NIFTY index option chain from NSE. |
| `get_sensex_option_chain()` | Fetch the SENSEX index option chain from BSE. |
| `get_bankex_option_chain()` | Fetch the BANKEX index option chain from BSE. |
| `get_equity_option_chain()` | Fetch the NSE equity option chain for any F&O stock. |
| `calculate_pcr()` | Calculate Put-Call Ratio (PCR) from NSE option chain OI and volume. |
| `calculate_max_pain()` | Calculate the max pain strike for an index option expiry. |
| `get_option_chain_depth()` | Per-strike option chain depth with summary analytics. |

### Options awareness (1)

| Tool | Description |
|---|---|
| `analyze_option_structure()` | Unified option chain analysis — OI walls, max pain, PCR, IV skew, and S/R levels. |

### Technicals (1)

| Tool | Description |
|---|---|
| `calculate_atr()` | Calculate the Average True Range (ATR) for a symbol. |

### Candlestick & chart patterns (2)

| Tool | Description |
|---|---|
| `detect_candlestick_patterns()` | Detect candlestick patterns for a symbol over a lookback window. |
| `detect_chart_patterns()` | Detect chart patterns for a symbol over a lookback window. |

### Chart analysis & images (4)

| Tool | Description |
|---|---|
| `analyze_chart()` | Analyze chart for a symbol — trend, structure, indicators, and key levels. |
| `get_price_chart()` | Returns candlestick price chart as base64 PNG. |
| `get_indicator_chart()` | Returns price + MACD + RSI chart as base64 PNG. |
| `get_option_chart()` | Returns Open Interest bar chart (Calls vs Puts) as base64 PNG. |

### Risk / sizing math (2)

| Tool | Description |
|---|---|
| `calculate_risk_reward()` | Calculate absolute risk, reward, and reward-to-risk ratio. |
| `calculate_position_size()` | Calculate position size from capital, risk %, entry, and stoploss. |

### Position sizing (1)

| Tool | Description |
|---|---|
| `size_options_trade()` | Calculate lot count for an options trade using fixed-risk sizing. |

### Dashboards (3)

| Tool | Description |
|---|---|
| `get_nifty_dashboard()` | Full NIFTY 50 market dashboard in a single call. |
| `get_banknifty_dashboard()` | Full BANK NIFTY market dashboard in a single call. |
| `get_sensex_dashboard()` | Full SENSEX market dashboard in a single call. |

### Trade planner & strategy builder (3)

| Tool | Description |
|---|---|
| `create_trade_plan()` | Generate a complete, read-only trade plan for a symbol. |
| `project_carry_cost()` | Estimate the time-value cost of holding an option position for more days. |
| `build_option_strategy()` | Build a concrete options strategy with specific strikes, expiry, and payoff. |

### Trade review (1)

| Tool | Description |
|---|---|
| `review_trade()` | Evaluate whether an existing trade's original thesis is still valid. |

### Market intelligence (3)

| Tool | Description |
|---|---|
| `get_india_vix()` | Get the current India VIX (volatility index) level and interpretation. |
| `get_global_pulse()` | Get a snapshot of global macro signals relevant to Indian equity markets. |
| `get_upcoming_events()` | List known macro events scheduled within the next N days. |

### Portfolio intelligence (2)

| Tool | Description |
|---|---|
| `get_portfolio_risk_report()` | Get a comprehensive risk report for your current portfolio. |
| `get_portfolio_exposure_breakdown()` | Get a fast exposure and concentration breakdown of your portfolio. |

### Catalyst / news (2)

| Tool | Description |
|---|---|
| `get_earnings_calendar()` | Get the next earnings date, EPS/revenue estimates, and upcoming corporate actions. |
| `check_move_news_correlation()` | Check whether a position's outsized move correlates with recent news. |

### Trade journal (8)

| Tool | Description |
|---|---|
| `log_trade()` | Log a new trade to your personal journal. |
| `close_trade()` | Close an open trade and calculate final P&L. |
| `get_open_trades()` | List all currently open trades. |
| `get_trade_history()` | Query trade history with optional filters and a performance summary. |
| `get_performance_analytics()` | Measure realized trading edge from your closed journal trades. |
| `get_strike_attempts()` | Today's strike-level attempt tally — observational only. |
| `get_orders()` | Fetch today's orders from your Zerodha account. |
| `sync_trades_from_zerodha()` | Sync today's executed Zerodha orders into your trade journal. |

### Trade recommendations & decision context (2)

| Tool | Description |
|---|---|
| `review_open_trades()` | Review all currently open journal positions against live market conditions. |
| `get_full_market_context()` | Consolidated single-call market context — replaces 6 separate tool calls. |

### Cost estimation (2)

| Tool | Description |
|---|---|
| `get_trade_cost_estimate()` | Estimate today's trade count and brokerage/STT costs. |
| `get_net_pnl_today()` | Real-time cost-adjusted net P&L for today. |

### Live position monitor (6)

| Tool | Description |
|---|---|
| `sync_positions()` | Manually trigger an immediate position sync from the broker(s) into the monitor. |
| `get_monitor_status()` | Return the background monitor's current state: tracked positions, thresholds, uptime. |
| `get_recent_alerts()` | Return WhatsApp alerts sent in the last N hours by the position monitor. |
| `get_market_alerts()` | Return market intelligence alerts sent in the last N hours. |
| `update_monitor_settings()` | Update the position monitor's alert thresholds without restarting the service. |
| `test_whatsapp_alert()` | Send a test WhatsApp message via CallMeBot to verify monitor alert delivery. |

### Market awareness — composite (1)

| Tool | Description |
|---|---|
| `get_market_awareness()` | Primary composite tool — call this first for any market analysis. |

### MCX commodities (1)

| Tool | Description |
|---|---|
| `check_benchmark_divergence()` | Compare an MCX commodity's move against its international benchmark. |

### Meta / server introspection (3)

| Tool | Description |
|---|---|
| `get_market_calendar()` | Canonical market calendar — date, trading status, expiries, holidays. |
| `get_capabilities()` | Returns the complete MCP manifest — capabilities and data boundaries. |
| `get_tool_health()` | Per-tool health snapshot. Call at session start to understand server state. |

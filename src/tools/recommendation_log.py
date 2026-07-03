"""
Phase 22 — Consolidated market context tools.

  get_full_market_context         — single call replacing 6 separate data calls
"""
from mcp.server.fastmcp import FastMCP

from src import meta as _meta

# Shared market context helpers (imported lazily so server startup stays fast)
def _market_context_data(symbol: str, include_options: bool) -> dict:
    from src.market import get_market
    from src.analysis import regime as _regime
    from src.intelligence.vix import get_india_vix
    from src.intelligence.events import get_upcoming_events

    ctx: dict = {}

    market = get_market()

    # Live quote
    try:
        ctx["quote"] = market.get_quote(symbol)
    except Exception as exc:
        ctx["quote"] = {"error": str(exc)}

    # OHLCV (today)
    try:
        ctx["ohlc"] = market.get_ohlc(symbol)
    except Exception as exc:
        ctx["ohlc"] = {"error": str(exc)}

    # Technical indicators (150-day strategy-grade lookback)
    try:
        from datetime import date, timedelta
        from src.technical import indicators as _ind
        today = date.today()
        start = (today - timedelta(days=150)).isoformat()
        end = (today + timedelta(days=1)).isoformat()
        candles = market.get_historical(symbol, start, end, "1d") or []
        if candles:
            closes = [c["close"] for c in candles]
            highs = [c["high"] for c in candles]
            lows = [c["low"] for c in candles]
            ctx["technicals"] = {
                "candles_used": len(closes),
                "last_close": round(closes[-1], 4),
                "rsi_14": _ind.rsi(closes, 14),
                "ema_20": _ind.ema(closes, 20),
                "ema_50": _ind.ema(closes, 50),
                "macd": _ind.macd(closes),
                "adx_14": _ind.adx(highs, lows, closes, 14),
                "atr_14": _ind.atr(highs, lows, closes, 14),
            }
        else:
            ctx["technicals"] = {"error": "no candle data"}
    except Exception as exc:
        ctx["technicals"] = {"error": str(exc)}

    # Market regime (uses cached technicals internally)
    try:
        ctx["regime"] = _regime.detect_market_regime(symbol)
    except Exception as exc:
        ctx["regime"] = {"error": str(exc)}

    # VIX
    try:
        ctx["vix"] = get_india_vix()
    except Exception as exc:
        ctx["vix"] = {"error": str(exc)}

    # Upcoming events (next 14 days)
    try:
        ctx["upcoming_events"] = get_upcoming_events(days_ahead=14)
    except Exception as exc:
        ctx["upcoming_events"] = {"error": str(exc)}

    # OI support/resistance (options — optional, only for index/F&O symbols)
    if include_options:
        try:
            from src.options import get_options_service
            from src.options.analytics import identify_support_resistance_from_oi
            svc = get_options_service()
            chain = svc.get_option_chain(symbol)
            spot = chain.get("records", {}).get("underlyingValue", 0)
            ctx["oi_levels"] = identify_support_resistance_from_oi(chain, spot)
        except Exception as exc:
            ctx["oi_levels"] = {"error": str(exc)}

    return ctx


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    def get_full_market_context(
        symbol: str,
        include_options: bool = False,
    ) -> dict:
        """Consolidated single-call market context — replaces 6 separate tool calls.

        Reduces context-window pressure by bundling: live quote, OHLCV,
        technical indicators (RSI/EMA/MACD/ADX/ATR), market regime descriptor,
        India VIX, and upcoming events into one response.

        Use this at the START of a session to build the market_snapshot dict
        before calling log_recommendation.

        Args:
            symbol: NSE symbol, index name, or yfinance ticker.
                    Examples: 'NIFTY', 'BANKNIFTY', 'NSE:INFY', 'INFY.NS'
            include_options: Set True for NIFTY/BANKNIFTY to include OI
                support/resistance levels. Adds 1-2 seconds for chain fetch.

        Returns:
            { quote, ohlc, technicals, regime, vix, upcoming_events }
            Each sub-dict has its own data and NaN detection.
            include_options=True also returns oi_levels.
        """
        data = _market_context_data(symbol, include_options)

        # Aggregate data quality from sub-components
        has_error = any(
            isinstance(v, dict) and "error" in v for v in data.values()
        )
        dq = _meta.DQ_PARTIAL if has_error else _meta.DQ_VALID

        m = _meta.build_meta(
            type_=_meta.TYPE_FACT,
            validation_status=_meta.VALIDATION_VERIFIED,
            data_quality=dq,
            source="yfinance",
            account_type="MARKET_DATA_ONLY",
            warning=(
                None if _meta.is_market_hours()
                else "Outside NSE session. Quotes reflect last traded price."
            ),
            limitations=[
                "Technicals from EOD-adjusted yfinance candles.",
                "Regime is INTERPRETATION — not a directional prediction.",
            ],
        )
        return _meta.wrap(data, m)

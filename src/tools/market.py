from typing import Optional
from mcp.server.fastmcp import FastMCP
from src.market import get_market
from src import meta as _meta
from src.market.symbols import normalize_symbol_extended as _norm, parse as _parse

# Valid yfinance intervals and a human-readable alias map
_YF_INTERVALS = {
    "1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h",
    "1d", "5d", "1wk", "1mo", "3mo",
}
_INTERVAL_ALIAS: dict[str, str] = {
    # kite-style → yfinance
    "minute": "1m",
    "3minute": "5m",
    "5minute": "5m",
    "10minute": "15m",
    "15minute": "15m",
    "30minute": "30m",
    "60minute": "60m",
    "day": "1d",
}


def _resolve_interval(interval: str) -> str:
    i = interval.lower().strip()
    if i in _YF_INTERVALS:
        return i
    if i in _INTERVAL_ALIAS:
        return _INTERVAL_ALIAS[i]
    raise ValueError(
        f"Unknown interval '{interval}'. Valid values: "
        + ", ".join(sorted(_YF_INTERVALS))
        + ". Kite-style aliases also accepted: "
        + ", ".join(sorted(_INTERVAL_ALIAS))
    )


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    def get_quote(instruments: list[str]) -> dict:
        """Return a full market quote for one or more instruments.

        Data source: NSELive (real-time NSE feed) for NSE stocks;
        Yahoo Finance for BSE stocks and indices.
        No authentication required.

        Args:
            instruments: List of 'EXCHANGE:SYMBOL' strings.
                         Examples: ['NSE:INFY', 'BSE:RELIANCE', 'NSE:NIFTY 50']
                         Raw yfinance tickers ('^NSEI', 'INFY.NS') also accepted.
        """
        market = get_market()
        data = {inst: market.get_quote(inst) for inst in instruments}
        dq = _meta.DQ_INVALID if any(
            isinstance(v, dict) and "error" in v for v in data.values()
        ) else _meta.DQ_VALID
        m = _meta.build_meta(
            type_=_meta.TYPE_FACT,
            validation_status=_meta.VALIDATION_VERIFIED,
            data_quality=dq,
            source="NSELive",
            account_type="MARKET_DATA_ONLY",
            warning=None if _meta.is_market_hours() else
                "Outside NSE session. Quote may be last traded price, not live.",
        )
        return _meta.wrap(data, m)

    @mcp.tool()
    def get_ltp(instruments: list[str]) -> dict:
        """Return just the last traded price for instruments — fastest quote call.

        Args:
            instruments: List of 'EXCHANGE:SYMBOL' strings.
                         Example: ['NSE:INFY', 'NSE:NIFTY 50']
        """
        market = get_market()
        data = {inst: {"last_price": market.get_ltp(inst)} for inst in instruments}
        m = _meta.build_meta(
            type_=_meta.TYPE_FACT,
            validation_status=_meta.VALIDATION_VERIFIED,
            data_quality=_meta.DQ_VALID,
            source="NSELive",
            account_type="MARKET_DATA_ONLY",
            warning=None if _meta.is_market_hours() else
                "Outside NSE session. LTP is last traded price before close.",
        )
        return _meta.wrap(data, m)

    @mcp.tool()
    def get_historical_data(
        symbol: str,
        from_date: str,
        to_date: str,
        interval: str = "1d",
    ) -> dict:
        """Return historical OHLCV candle data via Yahoo Finance.

        No authentication required. Data goes back years for daily candles;
        intraday data has a rolling 60-day limit from Yahoo Finance.

        Args:
            symbol: 'EXCHANGE:SYMBOL' (e.g. 'NSE:INFY', 'BSE:RELIANCE') or
                    raw yfinance ticker ('INFY.NS', '^NSEI').
            from_date: Start date as 'YYYY-MM-DD'.
            to_date: End date as 'YYYY-MM-DD'.
            interval: Candle size.
                      yfinance native: '1m','2m','5m','15m','30m','60m','90m',
                                       '1h','1d','5d','1wk','1mo','3mo'
                      Kite-style aliases also accepted: 'minute','5minute',
                                       '15minute','30minute','60minute','day'
        """
        sym, corrected, fmt = _norm(symbol, "get_historical_data")
        if not symbol.strip():
            return _meta.make_symbol_error(symbol, "get_historical_data")
        _norm_kw: dict = dict(
            symbol_corrected=corrected,
            symbol_original=symbol if corrected else None,
            symbol_normalized=sym if corrected else None,
            symbol_format_applied=fmt if corrected else None,
        )
        try:
            yf_interval = _resolve_interval(interval)
            candles = get_market().get_historical(sym, from_date, to_date, yf_interval)
            dq = _meta.DQ_VALID if candles else _meta.DQ_INVALID
            m = _meta.build_meta(
                type_=_meta.TYPE_FACT,
                validation_status=_meta.VALIDATION_VERIFIED,
                data_quality=dq,
                source="yfinance",
                account_type="MARKET_DATA_ONLY",
                limitations=["EOD-adjusted candles (split/dividend adjusted)."],
                **_norm_kw,
            )
            return _meta.wrap(candles, m)
        except ValueError as exc:
            m = _meta.build_meta(data_quality=_meta.DQ_INVALID)
            return _meta.wrap({"error": str(exc)}, m)

    @mcp.tool()
    def get_intraday_snapshot(symbol: str) -> dict:
        """Current intraday OHLC snapshot with range metrics.

        Returns open, high, low, current (last traded) price and derived
        distance metrics for the live session.

        Facts only — no signals, no confidence scores, no interpretations.

        Availability: time-gated — returns TOOL_TIME_GATED outside NSE
        session (09:15–15:30 IST on trading days).

        Args:
            symbol: 'NIFTY', 'BANKNIFTY', 'NSE:INFY', or a raw yfinance ticker.

        Limitations:
          - VWAP is not available from NSELive or yfinance fast_info and is
            not returned.
          - For indices, data comes from yfinance which updates every few
            minutes, not tick-by-tick.
          - distance_from_* metrics are null when high or low equals zero.
        """
        if not _meta.is_market_hours():
            return _meta.make_time_gated_error("get_intraday_snapshot")

        sym, corrected, fmt = _norm(symbol, "get_quote")
        if not symbol.strip():
            return _meta.make_symbol_error(symbol, "get_intraday_snapshot")
        _norm_kw: dict = dict(
            symbol_corrected=corrected,
            symbol_original=symbol if corrected else None,
            symbol_normalized=sym if corrected else None,
            symbol_format_applied=fmt if corrected else None,
        )

        try:
            q = get_market().get_quote(sym)
        except Exception as exc:
            m = _meta.build_meta(
                type_=_meta.TYPE_FACT,
                validation_status=_meta.VALIDATION_VERIFIED,
                data_quality=_meta.DQ_INVALID,
                source="NSELive/yfinance",
                account_type="MARKET_DATA_ONLY",
                **_norm_kw,
            )
            return _meta.wrap({"error": str(exc)}, m)

        current = q.get("last_price")
        open_ = q.get("open")
        high = q.get("high")
        low = q.get("low")
        source = q.get("source", "unknown")

        # Derived range metrics
        day_range_pct: float | None = None
        dist_high: float | None = None
        dist_low: float | None = None

        if high and low and low > 0:
            day_range_pct = round((high - low) / low * 100, 4)
        if current is not None and high and high > 0:
            dist_high = round((current - high) / high * 100, 4)
        if current is not None and low and low > 0:
            dist_low = round((current - low) / low * 100, 4)

        data = {
            "symbol": symbol.upper().strip().split(":")[-1],
            "open": open_,
            "high": high,
            "low": low,
            "current": current,
            "day_range_pct": day_range_pct,
            "distance_from_day_high": dist_high,
            "distance_from_day_low": dist_low,
            "distance_from_vwap": None,
            "source": source,
            "limitations": [
                "VWAP unavailable: not provided by NSELive or yfinance fast_info.",
                "distance_from_* is null when the high/low price is zero.",
                "For indices, data updates every few minutes via yfinance.",
            ],
        }

        data_age = 0 if source == "NSELive" else 120
        m = _meta.build_meta(
            type_=_meta.TYPE_FACT,
            validation_status=_meta.VALIDATION_VERIFIED,
            data_quality=_meta.DQ_VALID if current is not None else _meta.DQ_INVALID,
            source=source,
            account_type="MARKET_DATA_ONLY",
            data_age_seconds=data_age,
            stale_threshold_seconds=60,
            **_norm_kw,
        )
        return _meta.wrap(data, m)


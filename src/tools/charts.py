from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
from mcp.server.fastmcp import FastMCP

from src import meta as _meta
from src.chart_awareness import indicators as _ind
from src.chart_awareness.data_fetcher import fetch_candles
from src.chart_awareness.levels import detect_levels
from src.charts.config import CHART_SPECS
from src.charts.renderer import ChartRenderer
from src.charts.utils import get_pixel_dimensions
from src.options.analytics import _underlying
from src.options_awareness.engine import _get_chain_with_cache
from src.pattern_awareness.detector import ChartPatternDetector


async def get_price_chart_impl(
    symbol: str = "NIFTY",
    interval: str = "day",
    days: int = 90,
    theme: str = "dark",
    show_volume: bool = True,
    show_ema: bool = True,
    show_vwap: bool = False,
    show_bb: bool = False,
    show_patterns: bool = True,
) -> dict:
    symbol_upper = symbol.upper().strip()
    today = date.today()
    # Fetch extra days for indicators padding
    fetch_days = max(days + 50, 100)
    from_date = (today - timedelta(days=fetch_days)).isoformat()
    to_date = (today + timedelta(days=1)).isoformat()

    candles, data_source = await fetch_candles(symbol_upper, interval, from_date, to_date)
    if not candles:
        raise ValueError(f"No price candles found for {symbol_upper} ({interval})")

    df = pd.DataFrame(candles)
    df.columns = [c.lower() for c in df.columns]
    for col in ("open", "high", "low", "close"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["volume"] = pd.to_numeric(df.get("volume", 0), errors="coerce").fillna(0)

    # Slice to requested days
    cutoff = (today - timedelta(days=days)).isoformat()
    df_window = df[df["datetime"].astype(str) >= cutoff].copy()
    if df_window.empty:
        df_window = df.copy()

    # Compute levels and indicators on the window
    levels = detect_levels(df_window.to_dict("records"))
    ind_vals = _ind.compute(candles)

    patterns = []
    if show_patterns:
        detector = ChartPatternDetector()
        patterns = detector.detect_all(df_window, min_bars=20)

    renderer = ChartRenderer()
    img_b64 = renderer.render_price_chart(
        df=df_window.reset_index(drop=True),
        symbol=symbol_upper,
        indicators=ind_vals,
        levels=levels,
        patterns=patterns,
        theme=theme,
        show_volume=show_volume,
        show_ema=show_ema,
        show_vwap=show_vwap,
        show_bb=show_bb,
    )

    width, height = get_pixel_dimensions(CHART_SPECS["price"]["figsize"], CHART_SPECS["price"]["dpi"])

    result = {
        "symbol": symbol_upper,
        "interval": interval,
        "image": img_b64,
        "format": "png",
        "width": width,
        "height": height,
        "theme": theme,
        "data_source": data_source,
        "candles": len(df_window),
        "generated_at": date.today().isoformat(),
    }

    m = _meta.build_meta(
        type_=_meta.TYPE_FACT,
        validation_status=_meta.VALIDATION_COMPUTED,
        data_quality=_meta.DQ_VALID,
        source=data_source,
        account_type="MARKET_DATA_ONLY",
        limitations=["Matplotlib-rendered static charts without interactive zoom."],
    )
    return _meta.wrap(result, m)


async def get_indicator_chart_impl(
    symbol: str = "NIFTY",
    interval: str = "day",
    days: int = 90,
    theme: str = "dark",
) -> dict:
    symbol_upper = symbol.upper().strip()
    today = date.today()
    fetch_days = max(days + 50, 100)
    from_date = (today - timedelta(days=fetch_days)).isoformat()
    to_date = (today + timedelta(days=1)).isoformat()

    candles, data_source = await fetch_candles(symbol_upper, interval, from_date, to_date)
    if not candles:
        raise ValueError(f"No price candles found for {symbol_upper} ({interval})")

    df = pd.DataFrame(candles)
    df.columns = [c.lower() for c in df.columns]
    for col in ("open", "high", "low", "close"):
        df[col] = pd.to_numeric(df[col], errors="coerce")

    cutoff = (today - timedelta(days=days)).isoformat()
    df_window = df[df["datetime"].astype(str) >= cutoff].copy()
    if df_window.empty:
        df_window = df.copy()

    ind_vals = _ind.compute(candles)

    renderer = ChartRenderer()
    img_b64 = renderer.render_indicator_chart(
        df=df_window.reset_index(drop=True),
        symbol=symbol_upper,
        indicators=ind_vals,
        theme=theme,
    )

    width, height = get_pixel_dimensions(CHART_SPECS["indicator"]["figsize"], CHART_SPECS["indicator"]["dpi"])

    result = {
        "symbol": symbol_upper,
        "interval": interval,
        "image": img_b64,
        "format": "png",
        "width": width,
        "height": height,
        "theme": theme,
        "data_source": data_source,
        "generated_at": date.today().isoformat(),
    }

    m = _meta.build_meta(
        type_=_meta.TYPE_FACT,
        validation_status=_meta.VALIDATION_COMPUTED,
        data_quality=_meta.DQ_VALID,
        source=data_source,
        account_type="MARKET_DATA_ONLY",
        limitations=["Technical indicators computed using standard Wilders and standard EMA smoothing."],
    )
    return _meta.wrap(result, m)


async def get_option_chart_impl(
    symbol: str = "NIFTY",
    expiry: str | None = None,
    theme: str = "dark",
) -> dict:
    symbol_upper = symbol.upper().strip()
    chain, resolved_expiry, _ = _get_chain_with_cache(symbol_upper, expiry)
    spot = _underlying(chain) or 0.0

    renderer = ChartRenderer()
    img_b64 = renderer.render_option_chart(
        chain=chain,
        symbol=symbol_upper,
        spot=spot,
        theme=theme,
    )

    width, height = get_pixel_dimensions(CHART_SPECS["option"]["figsize"], CHART_SPECS["option"]["dpi"])

    result = {
        "symbol": symbol_upper,
        "expiry": resolved_expiry,
        "image": img_b64,
        "format": "png",
        "width": width,
        "height": height,
        "theme": theme,
        "generated_at": date.today().isoformat(),
    }

    m = _meta.build_meta(
        type_=_meta.TYPE_FACT,
        validation_status=_meta.VALIDATION_COMPUTED,
        data_quality=_meta.DQ_VALID,
        source="BSE" if symbol_upper in ("SENSEX", "BANKEX") else "NSE",
        account_type="MARKET_DATA_ONLY",
        limitations=["Open Interest snapshot with limited strike range surrounding spot."],
    )
    return _meta.wrap(result, m)


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    async def get_price_chart(
        symbol: str = "NIFTY",
        interval: str = "day",
        days: int = 90,
        theme: str = "dark",
        show_volume: bool = True,
        show_ema: bool = True,
        show_vwap: bool = False,
        show_bb: bool = False,
        show_patterns: bool = True,
    ) -> dict:
        """Returns candlestick price chart as base64 PNG.
        Includes EMA20/50/200, S/R levels, and pattern zones.

        symbol:          "NIFTY"|"BANKNIFTY"|"SENSEX"|"BANKEX"|stock
        interval:        1minute|5minute|15minute|30minute|60minute|day|week
        days:            lookback in calendar days (default 90)
        theme:           "dark"|"light" (default "dark")
        show_volume:     display volume panel (default True)
        show_ema:        overlay EMA20/50/200 lines (default True)
        show_vwap:       overlay VWAP (default False)
        show_bb:         overlay Bollinger Bands (default False)
        show_patterns:   highlight active chart patterns (default True)
        """
        return await get_price_chart_impl(
            symbol=symbol,
            interval=interval,
            days=days,
            theme=theme,
            show_volume=show_volume,
            show_ema=show_ema,
            show_vwap=show_vwap,
            show_bb=show_bb,
            show_patterns=show_patterns,
        )

    @mcp.tool()
    async def get_indicator_chart(
        symbol: str = "NIFTY",
        interval: str = "day",
        days: int = 90,
        theme: str = "dark",
    ) -> dict:
        """Returns price + MACD + RSI chart as base64 PNG.

        symbol:          "NIFTY"|"BANKNIFTY"|"SENSEX"|"BANKEX"|stock
        interval:        1minute|5minute|15minute|30minute|60minute|day|week
        days:            lookback in calendar days (default 90)
        theme:           "dark"|"light" (default "dark")
        """
        return await get_indicator_chart_impl(
            symbol=symbol,
            interval=interval,
            days=days,
            theme=theme,
        )

    @mcp.tool()
    async def get_option_chart(
        symbol: str = "NIFTY",
        expiry: str | None = None,
        theme: str = "dark",
    ) -> dict:
        """Returns Open Interest bar chart (Calls vs Puts) as base64 PNG.
        Highlights Spot price, Max Pain, and Call/Put Walls.

        symbol:          "NIFTY"|"BANKNIFTY"|"SENSEX"|"BANKEX"
        expiry:          Target expiry date (e.g. "2026-07-07"), defaults to near-week
        theme:           "dark"|"light" (default "dark")
        """
        return await get_option_chart_impl(
            symbol=symbol,
            expiry=expiry,
            theme=theme,
        )

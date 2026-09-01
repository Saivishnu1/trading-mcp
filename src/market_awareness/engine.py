from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from src.analysis.regime import detect_market_regime
from src.options import analytics

from .aggregator import MarketAggregator
from .narrator import MarketNarrator, get_calendar_index_key


class MarketAwarenessEngine:

    async def analyze(
        self,
        symbol: str,
        interval: str = "day",
        days: int = 90,
        include_options: bool = True,
        include_global: bool = True,
        include_patterns: bool = True,
    ) -> dict:
        symbol_upper = symbol.upper().strip()
        aggregator = MarketAggregator()
        narrator = MarketNarrator()

        # Run aggregation and regime detection concurrently
        loop = asyncio.get_running_loop()

        agg_task = aggregator.collect(
            symbol=symbol_upper,
            interval=interval,
            days=days,
            include_options=include_options,
            include_global=include_global,
            include_patterns=include_patterns,
        )

        regime_task = loop.run_in_executor(None, detect_market_regime, symbol_upper)

        raw_data, regime_res = await asyncio.gather(agg_task, regime_task, return_exceptions=True)

        missing_data = []

        if isinstance(raw_data, Exception):
            missing_data.append("aggregator")
            raw_data = {"missing_data": ["all"]}
        elif "missing_data" in raw_data:
            missing_data.extend(raw_data["missing_data"])

        if isinstance(regime_res, Exception) or (isinstance(regime_res, dict) and "error" in regime_res):
            missing_data.append("regime")
            regime_res = {}

        # Decompose aggregated components safely
        chart = raw_data.get("chart")
        if not isinstance(chart, dict) or "error" in chart:
            chart = {}

        candlestick = raw_data.get("candlestick")
        if not isinstance(candlestick, dict) or "error" in candlestick:
            candlestick = {}

        chart_pats = raw_data.get("chart_patterns")
        if not isinstance(chart_pats, dict) or "error" in chart_pats:
            chart_pats = {}

        options = raw_data.get("options")
        if not isinstance(options, dict) or "error" in options:
            options = {}

        global_pulse = raw_data.get("global")
        if not isinstance(global_pulse, dict) or "error" in global_pulse:
            global_pulse = {}

        vix = raw_data.get("vix")
        if not isinstance(vix, dict) or "error" in vix:
            vix = {}

        calendar = raw_data.get("calendar")
        if not isinstance(calendar, dict) or "error" in calendar:
            calendar = {}

        # Resolve spot price
        spot = None
        if options.get("spot") is not None:
            spot = options.get("spot")
        elif regime_res.get("price") is not None:
            spot = regime_res.get("price")
        elif chart.get("levels", {}).get("pivot", {}).get("pp") is not None:
            spot = chart.get("levels", {}).get("pivot", {}).get("pp")

        day_high = chart.get("day_high")
        day_low = chart.get("day_low")

        # Resolve expiry metrics
        idx_key = get_calendar_index_key(symbol_upper)
        expiries = calendar.get("expiries") or {}
        days_to_expiry_dict = calendar.get("days_to_expiry") or {}

        next_expiry = expiries.get(idx_key) or ""
        days_to_expiry_val = days_to_expiry_dict.get(idx_key)
        if days_to_expiry_val is not None:
            try:
                days_to_expiry_val = int(days_to_expiry_val)
            except (ValueError, TypeError):
                days_to_expiry_val = 0
        else:
            days_to_expiry_val = 0

        expiry_today = (days_to_expiry_val == 0) if next_expiry else False
        expiry_tomorrow = (days_to_expiry_val == 1) if next_expiry else False

        # Resolve regime mapping
        raw_regime = regime_res.get("regime")
        if raw_regime in ("BULL_TREND", "BEAR_TREND"):
            regime_val = "TRENDING"
        elif raw_regime == "BREAKOUT_POTENTIAL":
            regime_val = "BREAKOUT"
        else:
            regime_val = "RANGE_BOUND"

        # Resolve price vs EMA200
        ema200 = chart.get("indicators", {}).get("ema200")
        if spot is not None and ema200 is not None:
            price_vs_ema200 = "above" if spot > ema200 else "below"
        else:
            price_vs_ema200 = "below"

        # Safe Options properties
        opt_walls = options.get("walls") or {}
        opt_iv = options.get("iv") or {}
        opt_levels = options.get("oi_levels") or {}

        options_source = "none"
        if include_options and options and "error" not in options:
            options_source = "BSE" if symbol_upper in ("SENSEX", "BANKEX") else "NSE"

        # Priority 3 (2026-07-10) — surface max-pain pinning risk during
        # expiry week proactively instead of only via a manual deep pull.
        is_expiry_week_val = days_to_expiry_val <= 5 if next_expiry else False
        pinning = analytics.check_pinning_risk(spot, options.get("max_pain"), is_expiry_week_val)
        pinning_note = None
        if pinning["active"]:
            pinning_note = (
                f"Spot within {pinning['distance_points']:.0f} points of max pain "
                f"({options.get('max_pain'):.0f}) — expect range-bound chop until "
                f"expiry unwinds OI concentration."
            )

        # Construct final unified data dictionary
        final_data = {
            "symbol": symbol_upper,
            "spot": spot,
            "day_high": day_high,
            "day_low": day_low,
            "as_of": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "session_active": calendar.get("nse_session_active", False),
            "expiry": {
                "next": next_expiry,
                "days_to_expiry": days_to_expiry_val,
                "expiry_today": expiry_today,
                "expiry_tomorrow": expiry_tomorrow,
            },
            "market_structure": {
                "trend": chart.get("trend", {}).get("direction", "sideways"),
                "trend_strength": chart.get("trend", {}).get("strength", "weak"),
                "adx": chart.get("indicators", {}).get("adx") or regime_res.get("adx"),
                "regime": regime_val,
                "price_vs_ema20": chart.get("trend", {}).get("price_vs_ema20", "below"),
                "price_vs_ema50": chart.get("trend", {}).get("price_vs_ema50", "below"),
                "price_vs_ema200": price_vs_ema200,
            },
            "indicators": {
                "rsi": chart.get("indicators", {}).get("rsi") or regime_res.get("rsi"),
                "macd": chart.get("indicators", {}).get("macd"),
                "macd_signal": chart.get("indicators", {}).get("macd_signal"),
                "macd_histogram": chart.get("indicators", {}).get("macd_histogram"),
                "atr": chart.get("indicators", {}).get("atr") or regime_res.get("atr"),
                "ema20": chart.get("indicators", {}).get("ema20") or regime_res.get("ema20"),
                "ema50": chart.get("indicators", {}).get("ema50") or regime_res.get("ema50"),
                "ema200": ema200,
            },
            "levels": {
                "supports": [s["level"] for s in chart.get("levels", {}).get("supports", [])],
                "resistances": [r["level"] for r in chart.get("levels", {}).get("resistances", [])],
                "pivot": chart.get("levels", {}).get("pivot", {}),
            },
            "options": {
                "pcr": options.get("pcr") if include_options else None,
                "pcr_interpretation": options.get("pcr_interpretation", "") if include_options else "",
                "max_pain": options.get("max_pain") if include_options else None,
                "call_wall": opt_walls.get("call_wall") if include_options else None,
                "put_wall": opt_walls.get("put_wall") if include_options else None,
                "atm_iv": opt_iv.get("atm_iv") if include_options else None,
                "iv_skew": opt_iv.get("iv_skew") if include_options else None,
                "oi_supports": opt_levels.get("supports", []) if include_options else [],
                "oi_resistances": opt_levels.get("resistances", []) if include_options else [],
            },
            "patterns": {
                "candlestick": candlestick.get("patterns", []) if include_patterns else [],
                "chart": chart_pats.get("patterns", []) if include_patterns else [],
                "dominant_candle_bias": candlestick.get("summary", {}).get("dominant_bias", "neutral") if include_patterns else "neutral",
                "dominant_chart_bias": chart_pats.get("summary", {}).get("dominant_bias", "neutral") if include_patterns else "neutral",
            },
            "global": {
                "vix": vix.get("level") if include_global else None,
                "vix_interpretation": vix.get("interpretation", "") if include_global else "",
                "crude": global_pulse.get("assets", {}).get("crude_oil", {}).get("last") if include_global else None,
                "crude_change_pct": global_pulse.get("assets", {}).get("crude_oil", {}).get("change_pct") if include_global else None,
                "gold_change_pct": global_pulse.get("assets", {}).get("gold", {}).get("change_pct") if include_global else None,
                "dxy_change_pct": global_pulse.get("assets", {}).get("dxy", {}).get("change_pct") if include_global else None,
                "sp500_change_pct": global_pulse.get("assets", {}).get("sp500", {}).get("change_pct") if include_global else None,
                "overall_sentiment": global_pulse.get("overall_sentiment", "NEUTRAL") if include_global else "NEUTRAL",
            },
            "calendar": {
                "next_expiry": next_expiry,
                "days_to_expiry": days_to_expiry_val,
                "is_expiry_week": is_expiry_week_val,
                "upcoming_holidays": calendar.get("nse", {}).get("upcoming_holidays", []),
                "pinning_risk": {
                    "active": pinning["active"],
                    "distance_points": pinning["distance_points"],
                    "note": pinning_note,
                },
            },
            "data_sources": {
                "chart": chart.get("data_source", "none"),
                "options": options_source,
                "global": vix.get("source", "yfinance") if include_global else "none",
            },
            "missing_data": missing_data,
        }

        # Build observations with narrator
        raw_components = {
            "symbol": symbol_upper,
            "spot": spot,
            "chart": chart,
            "candlestick": candlestick,
            "chart_patterns": chart_pats,
            "options": options,
            "global": global_pulse,
            "vix": vix,
            "calendar": calendar,
        }

        final_data["observations"] = narrator.narrate(raw_components, missing_data)

        return final_data

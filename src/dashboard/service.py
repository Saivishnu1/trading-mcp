"""
Dashboard aggregator.

Pulls one option chain, one OHLCV series, then delegates to the existing
analytics/regime/indicator functions — no calculations are duplicated here.

Call graph (per dashboard build):
  _options_section  → OptionsService.get_option_chain (1 NSE fetch, 60s cached)
                       → analytics.calculate_pcr / max_pain / identify_sr
  _technicals_section → _load_closes (1 yfinance fetch)
                         → all indicators.*
  detect_market_regime → _analyze_technicals → _load_closes (1 yfinance fetch)
  generate_trade_setup → _analyze_technicals + detect_market_regime (2 fetches)
  recommend_strategy   → detect_market_regime (1 fetch)

yfinance returns from its in-process HTTP cache for repeated same-day,
same-ticker requests, so the duplicate analysis fetches are negligible.
"""

from __future__ import annotations

import logging

from src.analysis import regime as regime_mod
from src.options import analytics
from src.options.service import get_options_service
from src.technical import indicators
from src.tools.technicals import _load_closes

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def _options_section(symbol: str) -> tuple[dict, float | None]:
    """Fetch chain once; run all option analytics on it.

    Returns (section_dict, spot_price).
    """
    svc = get_options_service()
    chain = svc.get_option_chain(symbol)
    records = chain.get("records", {})
    spot: float | None = records.get("underlyingValue")
    expiry: str | None = (records.get("expiryDates") or [None])[0]

    pcr = analytics.calculate_pcr(chain, expiry)
    mp = analytics.calculate_max_pain(chain, expiry)
    sr = analytics.identify_support_resistance_from_oi(chain, expiry, top_n=5)

    ns = sr.get("nearest_support") or {}
    nr = sr.get("nearest_resistance") or {}

    return {
        "expiry": expiry,
        "pcr": pcr.get("pcr_oi"),
        "pcr_interpretation": pcr.get("interpretation"),
        "max_pain": mp.get("max_pain"),
        "distance_from_spot": mp.get("distance_from_spot"),
        "supports": [s["strike"] for s in sr.get("support_levels", [])],
        "resistances": [r["strike"] for r in sr.get("resistance_levels", [])],
        "nearest_support": ns.get("strike"),
        "nearest_resistance": nr.get("strike"),
    }, spot


def _technicals_section(symbol: str) -> tuple[dict, float | None]:
    """Single OHLCV fetch → full indicator set.

    Returns (section_dict, last_close).
    """
    closes, highs, lows = _load_closes(symbol, lookback_days=150)
    if not closes:
        return {"error": "no price data — check symbol"}, None

    adx_result = indicators.adx(highs, lows, closes, 14)
    return {
        "rsi": indicators.rsi(closes, 14),
        "ema20": indicators.ema(closes, 20),
        "ema50": indicators.ema(closes, 50),
        "macd": indicators.macd(closes),
        "adx": adx_result.get("adx"),
        "plus_di": adx_result.get("plus_di"),
        "minus_di": adx_result.get("minus_di"),
        "atr": indicators.atr(highs, lows, closes, 14),
    }, round(closes[-1], 4)


def _analysis_section(symbol: str) -> tuple[dict, dict, dict]:
    """Regime + trade setup + strategy.

    Returns (analysis_dict, trade_setup_dict, strategy_dict).
    """
    regime_result = regime_mod.detect_market_regime(symbol)
    setup_result = regime_mod.generate_trade_setup(symbol)
    strat_result = regime_mod.recommend_strategy(symbol)

    analysis: dict = (
        {"error": regime_result["error"]}
        if "error" in regime_result
        else {
            "regime": regime_result.get("regime"),
            "confidence": regime_result.get("confidence"),
            "signal": setup_result.get("signal") if "error" not in setup_result else None,
        }
    )

    trade_setup: dict = (
        {"error": setup_result["error"]}
        if "error" in setup_result
        else {
            "signal": setup_result.get("signal"),
            "confidence": setup_result.get("confidence"),
            "entry": setup_result.get("entry"),
            "stoploss": setup_result.get("stoploss"),
            "target": setup_result.get("target"),
            "entry_above": setup_result.get("entry_above"),
            "entry_below": setup_result.get("entry_below"),
            "bull_target": setup_result.get("bull_target"),
            "bear_target": setup_result.get("bear_target"),
            "reasoning": setup_result.get("reasoning", []),
        }
    )

    strategy: dict = (
        {"error": strat_result["error"]}
        if "error" in strat_result
        else {
            "recommended": strat_result.get("strategy"),
            "reason": strat_result.get("reason"),
        }
    )

    return analysis, trade_setup, strategy


# ---------------------------------------------------------------------------
# Summary generator
# ---------------------------------------------------------------------------

def _build_summary(
    symbol: str,
    spot: float | None,
    tech: dict,
    opts: dict,
    analysis: dict,
    signal: str | None,
) -> str:
    """Deterministic one-paragraph summary from key fields."""
    sym = symbol.upper()
    rsi: float = tech.get("rsi") or 50.0
    ema20: float | None = tech.get("ema20")
    ema50: float | None = tech.get("ema50")
    adx: float = tech.get("adx") or 0.0
    pcr: float | None = opts.get("pcr")
    regime: str = analysis.get("regime") or ""

    # Price vs moving averages
    if spot and ema20 and ema50:
        if spot > ema20 and spot > ema50:
            ma_clause = "trading above both key moving averages"
        elif spot < ema20 and spot < ema50:
            ma_clause = "trading below both key moving averages"
        elif spot > ema20:
            ma_clause = "above EMA20 but below EMA50"
        else:
            ma_clause = "below EMA20 but above EMA50"
    else:
        ma_clause = "in consolidation"

    # Options positioning
    if pcr is not None:
        if pcr > 1.3:
            opt_clause = "elevated put writing signals bullish options positioning"
        elif pcr > 1.0:
            opt_clause = "mildly bullish options positioning"
        elif pcr > 0.7:
            opt_clause = "neutral options positioning"
        else:
            opt_clause = "elevated call writing signals bearish options positioning"
    else:
        opt_clause = "options data unavailable"

    # Momentum
    if rsi > 65:
        mom_clause = "Momentum is strong and approaching overbought"
    elif rsi > 55:
        mom_clause = "Momentum is positive"
    elif rsi > 45:
        mom_clause = "Momentum is neutral"
    elif rsi > 35:
        mom_clause = "Momentum is weakening"
    else:
        mom_clause = "Momentum is oversold"

    # Trend strength
    if adx > 30:
        trend_clause = "trend strength is strong"
    elif adx > 20:
        trend_clause = "trend strength is moderate"
    else:
        trend_clause = "trend strength is low"

    # Directional bias
    bias_map = {
        "BUY": "Overall bias is bullish",
        "SELL": "Overall bias is bearish",
        "NEUTRAL_BULLISH": "Overall bias is mildly bullish",
        "NEUTRAL_BEARISH": "Overall bias is mildly bearish",
        "NEUTRAL": "No clear directional bias",
    }
    bias_clause = bias_map.get(signal or "", "Bias is undetermined")

    return (
        f"{sym} is {ma_clause}, with {opt_clause}. "
        f"{mom_clause} and {trend_clause}. "
        f"{bias_clause}."
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def build_dashboard(symbol: str) -> dict:
    """Build the full dashboard snapshot for *symbol*.

    Errors in individual sections are isolated — a failed options fetch does
    not prevent technicals or analysis from being returned.
    """
    # Options
    spot_chain: float | None = None
    try:
        opts, spot_chain = _options_section(symbol)
    except Exception as exc:
        logger.warning("options section failed for %s: %s", symbol, exc)
        opts = {"error": str(exc)}

    # Technicals
    spot_yf: float | None = None
    try:
        tech, spot_yf = _technicals_section(symbol)
    except Exception as exc:
        logger.warning("technicals section failed for %s: %s", symbol, exc)
        tech = {"error": str(exc)}

    spot = spot_chain or spot_yf

    # Analysis
    try:
        analysis, trade_setup, strategy = _analysis_section(symbol)
    except Exception as exc:
        logger.warning("analysis section failed for %s: %s", symbol, exc)
        err = {"error": str(exc)}
        analysis, trade_setup, strategy = err, err, err

    signal: str | None = (
        trade_setup.get("signal") if "error" not in trade_setup else None
    )

    summary = _build_summary(symbol, spot, tech, opts, analysis, signal)

    return {
        "symbol": symbol.upper(),
        "spot_price": spot,
        "options": opts,
        "technicals": tech,
        "analysis": analysis,
        "trade_setup": trade_setup,
        "strategy": strategy,
        "summary": summary,
    }

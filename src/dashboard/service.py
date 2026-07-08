"""
Dashboard aggregator.

Pulls one option chain, one OHLCV series, then delegates to the existing
analytics/regime/indicator functions — no calculations are duplicated here.

Call graph (per dashboard build):
  _options_section    → OptionsService/BSEOptionsService.get_option_chain
                         (1 fetch, cached) → analytics.calculate_pcr / max_pain / identify_sr
  _technicals_section → _load_closes (1 yfinance fetch) → all indicators.*
  _analysis_section   → detect_market_regime → _analyze_technicals (1 yfinance fetch)
                         → _build_market_structure (Phase 22F factual descriptor)

Dashboard output is factual only — no signal/confidence/trade_setup/strategy
fields (Phase 22F). Use create_trade_plan / build_option_strategy for
directional trade construction.

yfinance returns from its in-process HTTP cache for repeated same-day,
same-ticker requests, so the duplicate analysis fetches are negligible.
"""

from __future__ import annotations

import logging

from src.analysis import regime as regime_mod
from src.intelligence.events import get_upcoming_events, nearest_high_impact_days
from src.intelligence.risk import get_market_risk_score
from src.intelligence.vix import get_india_vix
from src.intelligence.global_pulse import get_global_pulse
from src.options import analytics
from src.options.bse_service import get_bse_options_service
from src.options.service import get_options_service
from src.technical import indicators
from src.tools.analysis import _build_market_structure
from src.tools.technicals import _load_closes

logger = logging.getLogger(__name__)

_BSE_INDICES = {"SENSEX", "BANKEX"}


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def _options_section(symbol: str) -> tuple[dict, float | None]:
    """Fetch chain once; run all option analytics on it.

    Returns (section_dict, spot_price).
    Returns empty defaults with a note when the chain is unavailable.
    """
    _UNAVAIL = {
        "expiry": None,
        "pcr": None,
        "pcr_interpretation": None,
        "max_pain": None,
        "distance_from_spot": None,
        "supports": [],
        "resistances": [],
        "nearest_support": None,
        "nearest_resistance": None,
        "note": "Option chain unavailable — market closed or data not yet loaded",
    }

    try:
        svc = get_bse_options_service() if symbol.upper() in _BSE_INDICES else get_options_service()
        chain = svc.get_option_chain(symbol) or {}
        records = chain.get("records") or {}
        spot: float | None = records.get("underlyingValue")
        expiry: str | None = (records.get("expiryDates") or [None])[0]

        if not records or not expiry:
            return {**_UNAVAIL, "note": "Option chain returned no data"}, spot

        pcr = analytics.calculate_pcr(chain, expiry) or {}
        mp = analytics.calculate_max_pain(chain, expiry) or {}
        sr = analytics.identify_support_resistance_from_oi(chain, expiry, top_n=5) or {}

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
    except Exception as exc:
        logger.warning("_options_section failed for %s: %s", symbol, exc)
        return {**_UNAVAIL, "error": str(exc)}, None


def _technicals_section(symbol: str) -> tuple[dict, float | None]:
    """Single OHLCV fetch → full indicator set.

    Returns (section_dict, last_close).
    """
    closes, highs, lows = _load_closes(symbol, lookback_days=150)
    if not closes:
        return {
            "error": (
                "no price data available — the data source may be temporarily "
                "unavailable or rate-limited; retry shortly, or verify the symbol "
                "if this persists"
            )
        }, None

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


def _analysis_section(symbol: str) -> dict:
    """Factual market structure only (Phase 22F) — no signal/confidence/trade_setup/strategy.

    Reuses the same regime → market_structure conversion as the
    detect_market_regime MCP tool, so the dashboard and the standalone
    tool never disagree on what counts as a "fact".
    """
    regime_result = regime_mod.detect_market_regime(symbol)
    structured = _build_market_structure(regime_result)
    if "error" in structured:
        return structured
    return {"market_structure": structured["market_structure"]}


# ---------------------------------------------------------------------------
# Summary generator
# ---------------------------------------------------------------------------

def _intelligence_section(symbol: str) -> dict:
    """Aggregate intelligence signals into a slim dashboard-friendly dict."""
    risk = get_market_risk_score(symbol)
    vix  = get_india_vix()
    glob = get_global_pulse()
    evts = get_upcoming_events(days_ahead=7)

    return {
        "vix": {
            "level":          vix.get("level"),
            "caution_level":  vix.get("caution_level"),
            "interpretation": vix.get("interpretation"),
        } if "error" not in vix else {"error": vix["error"]},
        "global_sentiment": glob.get("overall_sentiment") if "error" not in glob else None,
        "upcoming_events":  evts.get("events", [])[:3],   # top 3 nearest
        "risk_score": {
            "score":  risk.get("score"),
            "rating": risk.get("rating"),
        } if "error" not in risk else {"error": risk.get("error", "unavailable")},
    }


def _build_summary(
    symbol: str,
    spot: float | None,
    tech: dict,
    opts: dict,
    analysis: dict,
    intelligence: dict | None = None,
) -> str:
    """Deterministic one-paragraph summary — observed facts only (Phase 22F).

    No directional bias, recommendation, or predictive language.
    """
    sym = symbol.upper()
    rsi: float | None = tech.get("rsi")
    ema20: float | None = tech.get("ema20")
    ema50: float | None = tech.get("ema50")
    adx: float | None = tech.get("adx")
    macd: dict = tech.get("macd") or {}
    pcr: float | None = opts.get("pcr")
    pcr_interp: str | None = opts.get("pcr_interpretation")
    max_pain: float | None = opts.get("max_pain")
    ms: dict = analysis.get("market_structure") or {}
    adx_note = (ms.get("indicator_interpretation", {}).get("adx_note") or "").replace("_", " ")

    price_clause = f"{sym} at {spot:,.2f}." if spot is not None else f"{sym}:"

    # Price vs moving averages
    if spot is not None and ema20 is not None and ema50 is not None:
        above20, above50 = spot > ema20, spot > ema50
        if above20 and above50:
            ma_clause = f"Price above EMA20 ({ema20:,.2f}) and EMA50 ({ema50:,.2f})"
        elif not above20 and not above50:
            ma_clause = f"Price below EMA20 ({ema20:,.2f}) and EMA50 ({ema50:,.2f})"
        elif above20:
            ma_clause = f"Price above EMA20 ({ema20:,.2f}) but below EMA50 ({ema50:,.2f})"
        else:
            ma_clause = f"Price below EMA20 ({ema20:,.2f}) but above EMA50 ({ema50:,.2f})"
    else:
        ma_clause = "Moving averages unavailable"

    rsi_clause = f"RSI {rsi:.1f}" if rsi is not None else "RSI unavailable"

    histogram = macd.get("histogram")
    if histogram is not None:
        macd_clause = f"MACD {'positive' if histogram >= 0 else 'negative'}"
    else:
        macd_clause = "MACD unavailable"

    if adx is not None:
        adx_clause = f"ADX {adx:.1f}" + (f" {adx_note}" if adx_note else "")
    else:
        adx_clause = "ADX unavailable"

    if pcr is not None:
        pcr_clause = f"PCR {pcr:.2f}" + (f" {pcr_interp}" if pcr_interp else "")
    else:
        pcr_clause = "PCR unavailable"

    max_pain_clause = f"Max pain {max_pain:,.0f}." if max_pain is not None else "Max pain unavailable."

    # Event note (appended when HIGH-impact event is within 3 days) — factual only
    vix_clause = ""
    event_note = ""
    if intelligence:
        vix = intelligence.get("vix") or {}
        level = vix.get("level")
        if level is not None:
            vix_clause = f" VIX {level}."
        upcoming = intelligence.get("upcoming_events", [])
        days = nearest_high_impact_days(upcoming)
        if days is not None and days <= 3:
            first_high = next(
                (e for e in upcoming if e.get("impact") == "HIGH"), None
            )
            if first_high:
                event_note = f" Note: {first_high['description']} in {days} day(s)."

    return (
        f"{price_clause} {ma_clause}. "
        f"{rsi_clause}, {macd_clause}, {adx_clause}. "
        f"{pcr_clause}. {max_pain_clause}{vix_clause}{event_note}"
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
        analysis = _analysis_section(symbol)
    except Exception as exc:
        logger.warning("analysis section failed for %s: %s", symbol, exc)
        analysis = {"error": str(exc)}

    # Intelligence (isolated — failure must not break the rest)
    intelligence: dict | None = None
    try:
        intelligence = _intelligence_section(symbol)
    except Exception as exc:
        logger.warning("intelligence section failed for %s: %s", symbol, exc)

    summary = _build_summary(symbol, spot, tech, opts, analysis, intelligence)

    return {
        "symbol": symbol.upper(),
        "spot_price": spot,
        "options": opts,
        "technicals": tech,
        "analysis": analysis,
        "intelligence": intelligence,
        "summary": summary,
    }

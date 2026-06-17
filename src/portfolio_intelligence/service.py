"""
Portfolio Intelligence Service — Phase 11A.

Answers: "How exposed is my current portfolio to today's market conditions?"

Reuses existing modules — no indicator math is duplicated here:
  get_broker().holdings()       → demat positions (always LONG)
  get_broker().positions()      → intraday/carry-forward overlay
  review_trade()                → action, thesis_status, regime, signal, confidence
  get_market_risk_score()       → composite 0-100 risk score per symbol

All broker calls require an active Zerodha session.
All analysis calls degrade gracefully on failure (dashboard-style isolation).
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internals — position unification
# ---------------------------------------------------------------------------

def _get_all_positions() -> list[dict]:
    """Combine holdings + net positions into a unified list.

    Holdings (demat) take priority. Net positions are added only for symbols
    not already covered by holdings. Deduplication is by tradingsymbol.

    Raises RuntimeError if the broker call fails (no active session).
    """
    from src.broker import get_broker
    broker = get_broker()

    raw_holdings: list[dict] = broker.holdings()
    raw_positions: dict = broker.positions()

    seen: set[str] = set()
    result: list[dict] = []

    for h in raw_holdings:
        sym = (h.get("tradingsymbol") or "").upper()
        if not sym or (h.get("quantity") or 0) <= 0:
            continue
        seen.add(sym)
        qty = h.get("quantity", 0)
        last_price = h.get("last_price") or 0
        result.append({
            "symbol":        sym,
            "exchange":      h.get("exchange", "NSE"),
            "direction":     "LONG",
            "quantity":      qty,
            "avg_price":     h.get("average_price"),
            "last_price":    last_price,
            "current_value": round(qty * last_price, 2),
            "pnl":           h.get("pnl"),
            "source":        "holding",
        })

    for p in (raw_positions.get("net") or []):
        sym = (p.get("tradingsymbol") or "").upper()
        qty = p.get("quantity") or 0
        if not sym or qty == 0 or sym in seen:
            continue
        seen.add(sym)
        direction = "LONG" if qty > 0 else "SHORT"
        abs_qty = abs(qty)
        last_price = p.get("last_price") or 0
        result.append({
            "symbol":        sym,
            "exchange":      p.get("exchange", "NSE"),
            "direction":     direction,
            "quantity":      abs_qty,
            "avg_price":     p.get("average_price") or p.get("buy_price"),
            "last_price":    last_price,
            "current_value": round(abs_qty * last_price, 2),
            "pnl":           p.get("pnl") or p.get("unrealised"),
            "source":        "position",
        })

    return result


# ---------------------------------------------------------------------------
# Internals — per-position analysis
# ---------------------------------------------------------------------------

def _analyze_position(pos: dict) -> dict:
    """Run review_trade + get_market_risk_score for one position.

    Errors in either call are isolated — partial results are returned.
    """
    from src.review.reviewer import review_trade
    from src.intelligence.risk import get_market_risk_score

    sym = pos["symbol"]
    direction = pos["direction"]
    avg_price = pos.get("avg_price")

    analysis: dict = {
        "symbol":        sym,
        "direction":     direction,
        "quantity":      pos["quantity"],
        "current_value": pos["current_value"],
        "pnl":           pos.get("pnl"),
        # analysis fields — filled below
        "risk_score":    None,
        "risk_rating":   None,
        "regime":        None,
        "review_action": None,
        "thesis_status": None,
        "current_signal": None,
        "confidence":    None,
    }

    # --- risk score ---
    try:
        rs = get_market_risk_score(sym)
        if "error" not in rs:
            analysis["risk_score"]  = rs.get("score")
            analysis["risk_rating"] = rs.get("rating")
    except Exception as exc:
        logger.debug("risk score unavailable for %s: %s", sym, exc)

    # --- review (gives regime, signal, action, thesis) ---
    try:
        rv = review_trade(sym, direction=direction, entry_price=avg_price)
        if "error" in rv:
            analysis["review_error"] = rv["error"]
        else:
            analysis["regime"]         = rv.get("current_regime")
            analysis["review_action"]  = rv.get("action")
            analysis["thesis_status"]  = rv.get("thesis_status")
            analysis["current_signal"] = rv.get("current_signal")
            analysis["confidence"]     = rv.get("confidence")
            if avg_price is not None and "current_pnl_percent" in rv:
                analysis["pnl_percent"] = rv.get("current_pnl_percent")
    except Exception as exc:
        logger.debug("review_trade failed for %s: %s", sym, exc)
        analysis["review_error"] = str(exc)

    return analysis


# ---------------------------------------------------------------------------
# Internals — aggregation helpers
# ---------------------------------------------------------------------------

def _portfolio_risk_score(analyses: list[dict]) -> tuple[int, str]:
    """Value-weighted average risk score across all positions."""
    scored = [
        (a["risk_score"], a["current_value"])
        for a in analyses
        if a.get("risk_score") is not None
    ]
    if not scored:
        return 50, "MODERATE"
    total_value = sum(v for _, v in scored)
    if total_value > 0:
        avg = sum(s * v for s, v in scored) / total_value
    else:
        avg = sum(s for s, _ in scored) / len(scored)
    score = max(0, min(100, round(avg)))
    return score, _risk_rating(score)


def _risk_rating(score: int) -> str:
    if score < 30:
        return "LOW"
    if score < 60:
        return "MODERATE"
    if score < 80:
        return "HIGH"
    return "EXTREME"


def _diversification_score(positions: list[dict]) -> int:
    """HHI-based diversification: 0 (1 position) to ~100 (many equal positions)."""
    values = [p["current_value"] for p in positions if (p.get("current_value") or 0) > 0]
    if not values:
        return 0
    total = sum(values)
    if total == 0:
        return 0
    shares = [v / total for v in values]
    hhi = sum(s * s for s in shares)
    return round((1 - hhi) * 100)


def _concentration_risk(positions: list[dict]) -> dict:
    """Returns max single-position concentration and a flag if > 30%."""
    if not positions:
        return {
            "max_single_position_pct": 0,
            "concentrated":           False,
            "concentrated_symbol":    None,
        }
    total = sum(p.get("current_value") or 0 for p in positions)
    if total == 0:
        return {
            "max_single_position_pct": 0,
            "concentrated":           False,
            "concentrated_symbol":    None,
        }
    top = max(positions, key=lambda p: p.get("current_value") or 0)
    pct = round((top.get("current_value") or 0) / total * 100, 1)
    return {
        "max_single_position_pct": pct,
        "concentrated":           pct > 30,
        "concentrated_symbol":    top["symbol"] if pct > 30 else None,
    }


def _top_risks(analyses: list[dict]) -> list[dict]:
    """Top 3 positions by risk score, descending."""
    scored = [a for a in analyses if a.get("risk_score") is not None]
    scored.sort(key=lambda a: a["risk_score"], reverse=True)  # type: ignore[arg-type]
    return [
        {
            "symbol":        a["symbol"],
            "risk_score":    a["risk_score"],
            "risk_rating":   a.get("risk_rating"),
            "review_action": a.get("review_action"),
        }
        for a in scored[:3]
    ]


def _recommendations(
    port_score: int,
    analyses: list[dict],
    concentration: dict,
) -> list[str]:
    recs: list[str] = []

    exit_symbols   = [a["symbol"] for a in analyses if a.get("review_action") == "EXIT"]
    reduce_symbols = [a["symbol"] for a in analyses if a.get("review_action") == "REDUCE"]

    if exit_symbols:
        recs.append(
            f"Consider exiting: {', '.join(exit_symbols)} — thesis invalidated."
        )
    if reduce_symbols:
        recs.append(
            f"Consider reducing: {', '.join(reduce_symbols)} — thesis weakening."
        )
    if concentration.get("concentrated"):
        sym = concentration["concentrated_symbol"]
        pct = concentration["max_single_position_pct"]
        recs.append(
            f"{sym} represents {pct}% of portfolio — consider diversifying."
        )
    if port_score >= 80:
        recs.append(
            "Portfolio risk is EXTREME. Consider reducing overall exposure."
        )
    elif port_score >= 60:
        recs.append(
            "Portfolio risk is HIGH. Consider defined-risk structures or reduce size."
        )
    elif port_score < 30:
        recs.append("Portfolio risk is LOW. Conditions are favorable.")

    if not recs:
        recs.append("No immediate actions required. Continue monitoring.")
    return recs


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_portfolio_risk_report() -> dict:
    """Full portfolio risk report — per-position analysis + aggregated metrics."""
    try:
        positions = _get_all_positions()
    except Exception as exc:
        return {"error": str(exc)}

    if not positions:
        return {
            "total_positions":      0,
            "portfolio_risk_score": 50,
            "rating":               "MODERATE",
            "diversification_score": 0,
            "concentration_risk": {
                "max_single_position_pct": 0,
                "concentrated":           False,
                "concentrated_symbol":    None,
            },
            "top_risks":              [],
            "recommendations":        ["No positions found."],
            "per_position_analysis":  [],
        }

    analyses = [_analyze_position(p) for p in positions]

    port_score, port_rating = _portfolio_risk_score(analyses)
    div_score  = _diversification_score(positions)
    conc       = _concentration_risk(positions)
    top_risks  = _top_risks(analyses)
    recs       = _recommendations(port_score, analyses, conc)

    return {
        "total_positions":       len(positions),
        "portfolio_risk_score":  port_score,
        "rating":                port_rating,
        "diversification_score": div_score,
        "concentration_risk":    conc,
        "top_risks":             top_risks,
        "recommendations":       recs,
        "per_position_analysis": analyses,
    }


def get_portfolio_regime_analysis() -> dict:
    """Regime distribution and directional bias across the portfolio."""
    try:
        positions = _get_all_positions()
    except Exception as exc:
        return {"error": str(exc)}

    if not positions:
        return {
            "total_positions":           0,
            "positions_analyzed":        0,
            "regime_counts":             {},
            "dominant_regime":           None,
            "portfolio_directional_bias": "NEUTRAL",
            "per_position":              [],
            "summary":                   "No positions found.",
        }

    analyses = [_analyze_position(p) for p in positions]

    regime_counts: dict[str, int] = {}
    for a in analyses:
        r = a.get("regime") or "UNKNOWN"
        regime_counts[r] = regime_counts.get(r, 0) + 1

    _BULLISH = {"BULL_TREND", "NEUTRAL_BULLISH", "BREAKOUT_POTENTIAL"}
    _BEARISH = {"BEAR_TREND", "NEUTRAL_BEARISH"}
    bullish_count = sum(regime_counts.get(r, 0) for r in _BULLISH)
    bearish_count = sum(regime_counts.get(r, 0) for r in _BEARISH)

    if bullish_count > bearish_count:
        bias = "BULLISH"
    elif bearish_count > bullish_count:
        bias = "BEARISH"
    else:
        bias = "MIXED"

    known_regimes = {k: v for k, v in regime_counts.items() if k != "UNKNOWN"}
    dominant = (
        max(known_regimes, key=known_regimes.get)  # type: ignore[arg-type]
        if known_regimes
        else None
    )
    positions_analyzed = sum(1 for a in analyses if a.get("regime") is not None)

    return {
        "total_positions":            len(positions),
        "positions_analyzed":         positions_analyzed,
        "regime_counts":              regime_counts,
        "dominant_regime":            dominant,
        "portfolio_directional_bias": bias,
        "per_position": [
            {
                "symbol":  a["symbol"],
                "regime":  a.get("regime"),
                "signal":  a.get("current_signal"),
                "action":  a.get("review_action"),
            }
            for a in analyses
        ],
        "summary": (
            f"{len(positions)} positions analyzed. "
            f"Dominant regime: {dominant or 'unknown'}. "
            f"Portfolio bias: {bias}."
        ),
    }


def get_portfolio_exposure_breakdown() -> dict:
    """Exposure and concentration metrics — raw positions only, no analysis calls."""
    try:
        positions = _get_all_positions()
    except Exception as exc:
        return {"error": str(exc)}

    if not positions:
        return {
            "total_positions":   0,
            "long_positions":    0,
            "short_positions":   0,
            "long_exposure":     0.0,
            "short_exposure":    0.0,
            "net_exposure":      0.0,
            "total_invested":    0.0,
            "largest_position":  None,
            "top_exposures":     [],
            "concentration_metrics": {
                "max_single_position_pct": 0,
                "concentrated":           False,
                "concentrated_symbol":    None,
                "diversification_score":  0,
            },
        }

    long_pos  = [p for p in positions if p["direction"] == "LONG"]
    short_pos = [p for p in positions if p["direction"] == "SHORT"]

    long_exposure  = round(sum(p["current_value"] for p in long_pos), 2)
    short_exposure = round(sum(p["current_value"] for p in short_pos), 2)
    net_exposure   = round(long_exposure - short_exposure, 2)
    total_invested = round(long_exposure + short_exposure, 2)

    sorted_pos = sorted(positions, key=lambda p: p["current_value"], reverse=True)
    total      = sum(p["current_value"] for p in positions)
    largest    = sorted_pos[0]

    top_5 = [
        {
            "symbol":        p["symbol"],
            "direction":     p["direction"],
            "current_value": p["current_value"],
        }
        for p in sorted_pos[:5]
    ]

    conc     = _concentration_risk(positions)
    div_score = _diversification_score(positions)

    return {
        "total_positions":  len(positions),
        "long_positions":   len(long_pos),
        "short_positions":  len(short_pos),
        "long_exposure":    long_exposure,
        "short_exposure":   short_exposure,
        "net_exposure":     net_exposure,
        "total_invested":   total_invested,
        "largest_position": {
            "symbol":           largest["symbol"],
            "direction":        largest["direction"],
            "current_value":    largest["current_value"],
            "pct_of_portfolio": round(largest["current_value"] / total * 100, 1)
                                if total > 0 else 0,
        },
        "top_exposures": top_5,
        "concentration_metrics": {
            **conc,
            "diversification_score": div_score,
        },
    }

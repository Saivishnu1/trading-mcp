"""
Event Risk Score — Phase 11B.

Composite 0-100 score for company-specific catalyst risk:

  Earnings proximity   40%  (src.catalyst.earnings)
  News sentiment       30%  (src.catalyst.news)
  Market risk score    30%  (src.intelligence.risk — Phase 10, unchanged)

Higher score = more event-driven risk. Not a trading signal.

Also returns:
  confidence          — data availability weight (1.0 / 0.8 / 0.5 / 0.3)
  nearest_catalyst    — soonest catalyst by date within 30 days
  highest_impact_catalyst — highest-priority catalyst by CATALYST_PRIORITY

Cache TTL: 300 s (5 min).
"""
from __future__ import annotations

import logging
import threading
import time

from src.catalyst.constants import CATALYST_PRIORITY, _to_yf_ticker

logger = logging.getLogger(__name__)

_TTL = 300
_CACHE: dict[str, tuple[dict, float]] = {}
_LOCK = threading.Lock()

_CATALYST_HORIZON = 30  # days to look ahead for catalyst selection


# ---------------------------------------------------------------------------
# Component scorers
# ---------------------------------------------------------------------------

def _news_risk_score(sentiment_score: float, total_articles: int) -> tuple[int, str]:
    """Map aggregate news sentiment → risk score (0-100)."""
    if total_articles == 0:
        return 45, "No articles available — using neutral 45"
    if sentiment_score > 0.3:
        return 10, f"VERY_POSITIVE sentiment ({sentiment_score:+.2f}) → 10"
    if sentiment_score > 0.1:
        return 25, f"POSITIVE sentiment ({sentiment_score:+.2f}) → 25"
    if sentiment_score < -0.3:
        return 90, f"VERY_NEGATIVE sentiment ({sentiment_score:+.2f}) → 90"
    if sentiment_score < -0.1:
        return 65, f"NEGATIVE sentiment ({sentiment_score:+.2f}) → 65"
    return 45, f"NEUTRAL sentiment ({sentiment_score:+.2f}) → 45"


def _confidence(news_ok: bool, earnings_ok: bool, market_ok: bool) -> float:
    """Return confidence weight based on how many data sources are available."""
    if news_ok and earnings_ok and market_ok:
        return 1.0
    sources = sum([news_ok, earnings_ok, market_ok])
    if sources == 2:
        return 0.8
    if market_ok:
        return 0.5
    return 0.3


# ---------------------------------------------------------------------------
# Catalyst selection helpers
# ---------------------------------------------------------------------------

def _all_catalysts(earnings_result: dict) -> list[dict]:
    """Collect all upcoming catalysts from an earnings result dict."""
    catalysts: list[dict] = []

    # Earnings
    next_date = earnings_result.get("next_earnings_date")
    days_until = earnings_result.get("days_until_earnings")
    if next_date and days_until is not None and 0 <= days_until <= _CATALYST_HORIZON:
        catalysts.append({
            "type":       "EARNINGS",
            "date":       next_date,
            "days_until": days_until,
            "priority":   CATALYST_PRIORITY["EARNINGS"],
            "impact":     earnings_result.get("earnings_proximity_risk", "LOW"),
        })

    # Dividends
    for d in earnings_result.get("upcoming_dividends", []):
        if 0 <= d.get("days_until", 999) <= _CATALYST_HORIZON:
            catalysts.append({
                "type":       "DIVIDEND",
                "date":       d["ex_date"],
                "days_until": d["days_until"],
                "priority":   CATALYST_PRIORITY["DIVIDEND"],
                "impact":     "LOW",
                "amount":     d.get("amount"),
            })

    # Splits
    for s in earnings_result.get("upcoming_splits", []):
        if 0 <= s.get("days_until", 999) <= _CATALYST_HORIZON:
            catalysts.append({
                "type":       "SPLIT",
                "date":       s["ex_date"],
                "days_until": s["days_until"],
                "priority":   CATALYST_PRIORITY["SPLIT"],
                "impact":     "MEDIUM",
                "ratio":      s.get("ratio"),
            })

    return catalysts


def _nearest_catalyst(catalysts: list[dict]) -> dict | None:
    """Return the catalyst with the smallest days_until."""
    if not catalysts:
        return None
    return min(catalysts, key=lambda c: c["days_until"])


def _highest_impact_catalyst(catalysts: list[dict]) -> dict | None:
    """Return the catalyst with the highest CATALYST_PRIORITY score."""
    if not catalysts:
        return None
    return max(catalysts, key=lambda c: c["priority"])


# ---------------------------------------------------------------------------
# Rating + recommendation
# ---------------------------------------------------------------------------

def _rating(score: int) -> str:
    if score < 30:
        return "LOW"
    if score < 60:
        return "MODERATE"
    if score < 80:
        return "HIGH"
    return "EXTREME"


def _recommendation(score: int, nearest: dict | None, symbol: str) -> str:
    catalyst_note = ""
    if nearest is not None:
        ctype = nearest["type"].capitalize()
        days = nearest["days_until"]
        catalyst_note = (
            f" {ctype} event in {days} day(s) —"
            " consider defined-risk structures."
        )

    if score < 30:
        return f"Event risk is LOW. No imminent catalyst concerns for {symbol}.{catalyst_note}"
    if score < 60:
        return (
            f"Moderate event risk for {symbol}. Standard risk management applies.{catalyst_note}"
        )
    if score < 80:
        return (
            f"Elevated event risk for {symbol}. Reduce size or use defined-risk structures.{catalyst_note}"
        )
    return (
        f"Extreme event risk for {symbol}. Avoid new trades or use minimal size.{catalyst_note}"
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_event_risk(symbol: str) -> dict:
    """Composite event risk score (0-100) for a symbol.

    Weights: earnings proximity 40% + news sentiment 30% + market risk 30%.

    Returns:
      event_risk_score       — 0 to 100
      event_risk_rating      — LOW / MODERATE / HIGH / EXTREME
      confidence             — 0.3-1.0 based on data availability
      components             — per-component scores and weights
      factors                — plain-English breakdown
      nearest_catalyst       — soonest upcoming catalyst within 30 days
      highest_impact_catalyst — highest-priority upcoming catalyst
      recommendation         — actionable guidance

    No authentication required. Market risk score (Phase 10) is a sub-component.
    """
    sym = symbol.upper().strip().split(":")[-1]
    yf_ticker = _to_yf_ticker(symbol)
    cache_key = f"event_risk_{yf_ticker}"

    with _LOCK:
        if cache_key in _CACHE:
            result, ts = _CACHE[cache_key]
            if time.monotonic() - ts < _TTL:
                return result

    # --- earnings component (40%) ---
    earnings_score: int = 10
    earnings_ok: bool = False
    earnings_desc: str = "Earnings unavailable — using LOW proxy 10"
    earnings_result: dict = {}

    try:
        from src.catalyst.earnings import get_earnings_calendar
        earnings_result = get_earnings_calendar(symbol)
        if "error" not in earnings_result:
            earnings_score = earnings_result.get("earnings_proximity_score", 10)
            prox_risk = earnings_result.get("earnings_proximity_risk", "LOW")
            days = earnings_result.get("days_until_earnings")
            if days is not None:
                earnings_desc = (
                    f"{days} days until earnings → {prox_risk} → {earnings_score}"
                )
            else:
                earnings_desc = f"No upcoming earnings date → {prox_risk} → {earnings_score}"
            earnings_ok = True
    except Exception as exc:
        logger.debug("earnings component failed for %s: %s", sym, exc)

    # --- news sentiment component (30%) ---
    news_score: int = 45
    news_ok: bool = False
    news_desc: str = "News unavailable — using neutral 45"

    try:
        from src.catalyst.news import _aggregate_sentiment, get_symbol_news
        news_result = get_symbol_news(symbol)
        if "error" not in news_result:
            sentiment_data = _aggregate_sentiment(news_result.get("headlines", []))
            news_score, news_desc = _news_risk_score(
                sentiment_data["sentiment_score"],
                sentiment_data["total_articles"],
            )
            news_ok = True
    except Exception as exc:
        logger.debug("news component failed for %s: %s", sym, exc)

    # --- market risk component (30%, Phase 10) ---
    market_score: int = 50
    market_ok: bool = False
    market_desc: str = "Market risk unavailable — using neutral 50"

    try:
        from src.intelligence.risk import get_market_risk_score
        mkt = get_market_risk_score(sym)
        if "error" not in mkt:
            market_score = mkt.get("score", 50)
            market_rating = mkt.get("rating", "MODERATE")
            market_desc = f"Market risk score {market_score} ({market_rating})"
            market_ok = True
    except Exception as exc:
        logger.debug("market risk component failed for %s: %s", sym, exc)

    # --- composite score ---
    score = round(
        earnings_score * 0.40
        + news_score    * 0.30
        + market_score  * 0.30
    )
    score = max(0, min(100, score))

    conf = _confidence(news_ok, earnings_ok, market_ok)

    # --- catalyst timeline ---
    catalysts = _all_catalysts(earnings_result)
    nearest = _nearest_catalyst(catalysts)
    highest = _highest_impact_catalyst(catalysts)

    result = {
        "symbol":             sym,
        "event_risk_score":   score,
        "event_risk_rating":  _rating(score),
        "confidence":         conf,
        "components": {
            "earnings_proximity_score": earnings_score,
            "news_sentiment_score":     news_score,
            "market_risk_score":        market_score,
            "weights": {
                "earnings": 0.40,
                "news":     0.30,
                "market":   0.30,
            },
        },
        "factors": [
            f"Earnings (40%): {earnings_desc}",
            f"News (30%): {news_desc}",
            f"Market (30%): {market_desc}",
        ],
        "nearest_catalyst":         nearest,
        "highest_impact_catalyst":  highest,
        "recommendation": _recommendation(score, nearest, sym),
    }

    with _LOCK:
        _CACHE[cache_key] = (result, time.monotonic())
    return result

"""
Symbol news + sentiment — Phase 11B.

Fetches recent news headlines for a symbol via yfinance.Ticker.news and
applies keyword-based per-article sentiment scoring. No ML, no API keys.

Aggregate sentiment is exposed as _aggregate_sentiment() so event_risk.py
can consume it without triggering a second yfinance fetch (news is cached).

Cache TTL: 1800 s (30 min).
"""
from __future__ import annotations

import logging
import threading
import time

from src.catalyst.constants import (
    _NEGATIVE_KEYWORDS,
    _POSITIVE_KEYWORDS,
    _to_yf_ticker,
)

logger = logging.getLogger(__name__)

_TTL = 1800
_CACHE: dict[str, tuple[dict, float]] = {}
_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# yfinance integration — patchable factory
# ---------------------------------------------------------------------------

def _get_ticker(yf_ticker: str):
    import yfinance as yf
    return yf.Ticker(yf_ticker)


# ---------------------------------------------------------------------------
# Sentiment helpers
# ---------------------------------------------------------------------------

def _article_sentiment(title: str) -> str:
    """Classify a single headline as POSITIVE, NEGATIVE, or NEUTRAL."""
    words = set(title.lower().split())
    pos = len(words & _POSITIVE_KEYWORDS)
    neg = len(words & _NEGATIVE_KEYWORDS)
    if pos > neg:
        return "POSITIVE"
    if neg > pos:
        return "NEGATIVE"
    return "NEUTRAL"


def _sentiment_label(score: float) -> str:
    if score > 0.3:
        return "VERY_POSITIVE"
    if score > 0.1:
        return "POSITIVE"
    if score < -0.3:
        return "VERY_NEGATIVE"
    if score < -0.1:
        return "NEGATIVE"
    return "NEUTRAL"


def _aggregate_sentiment(headlines: list[dict]) -> dict:
    """Compute aggregate sentiment from a list of headline dicts.

    Each dict must have a 'sentiment' key (POSITIVE/NEGATIVE/NEUTRAL).
    Returns sentiment, sentiment_score (−1.0 to +1.0), counts, and top headlines.
    Called by event_risk.py without making a second yfinance request.
    """
    if not headlines:
        return {
            "sentiment":        "NEUTRAL",
            "sentiment_score":  0.0,
            "positive_count":   0,
            "negative_count":   0,
            "neutral_count":    0,
            "total_articles":   0,
            "summary":          "No news articles available.",
            "top_positive_headline": None,
            "top_negative_headline": None,
        }

    pos = [h for h in headlines if h.get("sentiment") == "POSITIVE"]
    neg = [h for h in headlines if h.get("sentiment") == "NEGATIVE"]
    neu = [h for h in headlines if h.get("sentiment") == "NEUTRAL"]
    total = len(headlines)

    score = round((len(pos) - len(neg)) / total, 4)
    label = _sentiment_label(score)

    dominant = "positive" if len(pos) >= len(neg) else "negative"
    dominant_count = max(len(pos), len(neg))
    summary = (
        f"Recent news is predominantly {dominant} "
        f"({dominant_count}/{total} articles)."
    )

    return {
        "sentiment":             label,
        "sentiment_score":       score,
        "positive_count":        len(pos),
        "negative_count":        len(neg),
        "neutral_count":         len(neu),
        "total_articles":        total,
        "summary":               summary,
        "top_positive_headline": pos[0]["title"] if pos else None,
        "top_negative_headline": neg[0]["title"] if neg else None,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_symbol_news(symbol: str, count: int = 10) -> dict:
    """Fetch recent news headlines for *symbol* with per-article sentiment.

    Returns up to *count* articles. Each article includes title, publisher,
    published_at (ISO-8601), link, and sentiment (POSITIVE/NEGATIVE/NEUTRAL).

    For index symbols (NIFTY, BANKNIFTY) news reflects broad market coverage.

    Cache TTL: 1800 s.
    """
    yf_ticker = _to_yf_ticker(symbol)
    count = max(1, min(count, 50))
    cache_key = f"news_{yf_ticker}_{count}"

    with _LOCK:
        if cache_key in _CACHE:
            result, ts = _CACHE[cache_key]
            if time.monotonic() - ts < _TTL:
                return result

    try:
        ticker = _get_ticker(yf_ticker)
        raw_news = ticker.news or []
    except Exception as exc:
        logger.debug("yfinance news fetch failed for %s: %s", yf_ticker, exc)
        return {
            "symbol":    symbol.upper(),
            "yf_ticker": yf_ticker,
            "count":     0,
            "headlines": [],
            "error":     str(exc),
        }

    headlines = []
    for item in raw_news[:count]:
        title = item.get("title") or ""
        ts_unix = item.get("providerPublishTime") or item.get("published") or 0
        try:
            import datetime
            published_at = (
                datetime.datetime.fromtimestamp(ts_unix, tz=datetime.UTC)
                .strftime("%Y-%m-%dT%H:%M:%SZ")
                if ts_unix
                else None
            )
        except Exception:
            published_at = None

        headlines.append({
            "title":        title,
            "publisher":    item.get("publisher") or item.get("source") or None,
            "published_at": published_at,
            "link":         item.get("link") or item.get("url") or None,
            "sentiment":    _article_sentiment(title),
        })

    result = {
        "symbol":    symbol.upper(),
        "yf_ticker": yf_ticker,
        "count":     len(headlines),
        "headlines": headlines,
    }

    with _LOCK:
        _CACHE[cache_key] = (result, time.monotonic())
    return result


# ---------------------------------------------------------------------------
# Move-news correlation (Priority B11, 2026-07-11)
# ---------------------------------------------------------------------------

def check_move_news_correlation(symbol: str, threshold_pct: float = 3.0) -> dict:
    """When *symbol*'s intraday move exceeds threshold_pct, surface the top
    headlines so a large move doesn't require a manual web search to explain
    (the exact gap hit repeatedly in one session — Iran ceasefire status,
    Qatar LNG halt, OPEC+ output changes only found by hand).

    Move % is last_price vs. previous_close (the same reference convention
    already used by check_index_move in src/monitor/conditions.py and
    scheduler.py's EOD summary, not a strict "since today's open" figure).

    Returns {"symbol", "change_pct", "triggered", "headlines"} — headlines
    is empty when not triggered (no news fetch is made in that case, since
    it's the whole point of gating on the threshold).

    Caveat: yfinance's .news feed is NSE/global-equity-oriented and has
    known-thin coverage for MCX futures tickers — this works well for
    NIFTY/SENSEX/equity positions but may return empty/sparse results for
    MCX commodity symbols.
    """
    try:
        from src.market import get_market
        quote = get_market().get_quote(symbol)
        last_price = quote.get("last_price")
        previous_close = quote.get("previous_close")
    except Exception as exc:
        logger.debug("check_move_news_correlation quote fetch failed for %s: %s", symbol, exc)
        return {"symbol": symbol.upper(), "error": str(exc)}

    if not last_price or not previous_close:
        return {"symbol": symbol.upper(), "error": "no_quote_data"}

    change_pct = round((last_price - previous_close) / previous_close * 100, 2)
    triggered = abs(change_pct) >= threshold_pct

    result = {
        "symbol": symbol.upper(),
        "change_pct": change_pct,
        "triggered": triggered,
        "headlines": [],
    }
    if not triggered:
        return result

    news = get_symbol_news(symbol, count=5)
    result["headlines"] = news.get("headlines", [])[:2]
    return result

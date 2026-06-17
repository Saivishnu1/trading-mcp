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
    is_index,
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
                datetime.datetime.fromtimestamp(ts_unix, tz=datetime.timezone.utc)
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

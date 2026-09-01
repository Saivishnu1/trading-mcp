"""Tests for src/catalyst/news.py"""
from __future__ import annotations

import time
import types

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_ticker(news_items=None, raises=False):
    """Return a mock object that satisfies _get_ticker() usage in news.py."""
    class _Ticker:
        @property
        def news(self):
            if raises:
                raise RuntimeError("yfinance unavailable")
            return news_items if news_items is not None else []
    return _Ticker()


def _headline(title, publisher="ET", ts=1718438400, link="https://example.com"):
    return {
        "title": title,
        "publisher": publisher,
        "providerPublishTime": ts,
        "link": link,
    }


# ---------------------------------------------------------------------------
# TestToYfTicker — symbol normalisation (constants._to_yf_ticker)
# ---------------------------------------------------------------------------

class TestToYfTicker:
    def _resolve(self, sym):
        from src.catalyst.constants import _to_yf_ticker
        return _to_yf_ticker(sym)

    def test_bare_equity(self):
        assert self._resolve("INFY") == "INFY.NS"

    def test_exchange_prefix_stripped(self):
        assert self._resolve("NSE:INFY") == "INFY.NS"

    def test_bse_prefix_stripped(self):
        assert self._resolve("BSE:RELIANCE") == "RELIANCE.NS"

    def test_already_suffixed_idempotent(self):
        assert self._resolve("INFY.NS") == "INFY.NS"

    def test_bo_suffix_preserved(self):
        assert self._resolve("INFY.BO") == "INFY.BO"

    def test_nifty_alias(self):
        assert self._resolve("NIFTY") == "^NSEI"

    def test_banknifty_alias(self):
        assert self._resolve("BANKNIFTY") == "^NSEBANK"

    def test_sensex_alias(self):
        assert self._resolve("SENSEX") == "^BSESN"

    def test_finnifty_alias(self):
        assert self._resolve("FINNIFTY") == "^CNXFIN"

    def test_case_insensitive(self):
        assert self._resolve("infy") == "INFY.NS"

    def test_nifty50_alias(self):
        assert self._resolve("NIFTY50") == "^NSEI"

    def test_nifty_space_alias(self):
        assert self._resolve("NIFTY 50") == "^NSEI"

    def test_raw_yf_ticker_passed_through(self):
        assert self._resolve("^NSEI") == "^NSEI"

    def test_futures_ticker_passed_through(self):
        assert self._resolve("CL=F") == "CL=F"


# ---------------------------------------------------------------------------
# TestArticleSentiment
# ---------------------------------------------------------------------------

class TestArticleSentiment:
    def _sent(self, title):
        from src.catalyst.news import _article_sentiment
        return _article_sentiment(title)

    def test_positive_keyword(self):
        assert self._sent("Infosys beats Q1 estimates") == "POSITIVE"

    def test_negative_keyword(self):
        assert self._sent("TCS reports loss in Q2") == "NEGATIVE"

    def test_neutral_no_keywords(self):
        assert self._sent("HDFC Bank announces AGM date") == "NEUTRAL"

    def test_mixed_positive_wins(self):
        # more positive words than negative
        assert self._sent("Record profit growth beat estimates") == "POSITIVE"

    def test_mixed_negative_wins(self):
        assert self._sent("Fraud probe penalty loss") == "NEGATIVE"

    def test_empty_title(self):
        assert self._sent("") == "NEUTRAL"

    def test_case_insensitive_matching(self):
        assert self._sent("RECORD PROFIT FOR Q1") == "POSITIVE"


# ---------------------------------------------------------------------------
# TestAggregateSentiment
# ---------------------------------------------------------------------------

class TestAggregateSentiment:
    def _agg(self, headlines):
        from src.catalyst.news import _aggregate_sentiment
        return _aggregate_sentiment(headlines)

    def test_empty_list_returns_neutral(self):
        result = self._agg([])
        assert result["sentiment"] == "NEUTRAL"
        assert result["sentiment_score"] == 0.0
        assert result["total_articles"] == 0
        assert result["top_positive_headline"] is None
        assert result["top_negative_headline"] is None

    def test_all_positive(self):
        headlines = [
            {"title": "Beat", "sentiment": "POSITIVE"},
            {"title": "Growth", "sentiment": "POSITIVE"},
        ]
        result = self._agg(headlines)
        assert result["positive_count"] == 2
        assert result["negative_count"] == 0
        assert result["sentiment_score"] == 1.0
        assert result["sentiment"] in ("VERY_POSITIVE", "POSITIVE")

    def test_all_negative(self):
        headlines = [
            {"title": "Loss", "sentiment": "NEGATIVE"},
            {"title": "Fraud", "sentiment": "NEGATIVE"},
        ]
        result = self._agg(headlines)
        assert result["negative_count"] == 2
        assert result["sentiment_score"] == -1.0
        assert result["sentiment"] in ("VERY_NEGATIVE", "NEGATIVE")

    def test_mixed_score_calculation(self):
        # 3 positive, 1 negative, 0 neutral → score = (3-1)/4 = 0.5
        headlines = [
            {"title": "A", "sentiment": "POSITIVE"},
            {"title": "B", "sentiment": "POSITIVE"},
            {"title": "C", "sentiment": "POSITIVE"},
            {"title": "D", "sentiment": "NEGATIVE"},
        ]
        result = self._agg(headlines)
        assert result["sentiment_score"] == 0.5
        assert result["sentiment"] == "VERY_POSITIVE"

    def test_very_positive_threshold(self):
        headlines = [{"title": f"p{i}", "sentiment": "POSITIVE"} for i in range(4)]
        result = self._agg(headlines)
        assert result["sentiment"] == "VERY_POSITIVE"
        assert result["sentiment_score"] == 1.0

    def test_very_negative_threshold(self):
        headlines = [{"title": f"n{i}", "sentiment": "NEGATIVE"} for i in range(4)]
        result = self._agg(headlines)
        assert result["sentiment"] == "VERY_NEGATIVE"

    def test_top_positive_headline(self):
        headlines = [
            {"title": "Bad news", "sentiment": "NEGATIVE"},
            {"title": "Good news", "sentiment": "POSITIVE"},
        ]
        result = self._agg(headlines)
        assert result["top_positive_headline"] == "Good news"
        assert result["top_negative_headline"] == "Bad news"

    def test_neutral_count(self):
        headlines = [
            {"title": "A", "sentiment": "NEUTRAL"},
            {"title": "B", "sentiment": "NEUTRAL"},
            {"title": "C", "sentiment": "POSITIVE"},
        ]
        result = self._agg(headlines)
        assert result["neutral_count"] == 2
        assert result["total_articles"] == 3

    def test_summary_string_present(self):
        headlines = [{"title": "X", "sentiment": "POSITIVE"}]
        result = self._agg(headlines)
        assert isinstance(result["summary"], str)
        assert len(result["summary"]) > 0


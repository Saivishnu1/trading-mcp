"""
Catalyst Intelligence regression guards — Phase 11B.

  ER-1: yfinance raises for symbol → {"error": "..."} dict, no exception propagates
  ER-2: Ticker.news returns empty list → valid response with count:0, headlines:[]
  ER-3: Ticker.calendar returns None → valid response, next_earnings_date:null
  ER-4: Both news and earnings fail → get_event_risk falls back to market only,
         confidence=0.5, still returns a valid structured response
  ER-5: Symbol passed as NSE:INFY, INFY.NS, or INFY → all resolve to INFY.NS
         (idempotent normalisation, no duplication)
"""
from __future__ import annotations

from datetime import date, timedelta


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _future_date(days: int) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


class _MockActions:
    empty = True
    def iterrows(self): return iter([])


def _raising_ticker():
    class _T:
        @property
        def news(self): raise RuntimeError("yfinance unavailable")
        @property
        def calendar(self): raise RuntimeError("yfinance unavailable")
        @property
        def actions(self): raise RuntimeError("yfinance unavailable")
    return _T()


def _empty_ticker():
    class _T:
        news = []
        calendar = None
        actions = _MockActions()
    return _T()


def _clear_caches():
    import src.catalyst.news as nm
    import src.catalyst.earnings as em
    import src.catalyst.event_risk as erm
    with nm._LOCK: nm._CACHE.clear()
    with em._LOCK: em._CACHE.clear()
    with erm._LOCK: erm._CACHE.clear()


# ---------------------------------------------------------------------------
# ER-1: yfinance raises → error dict, no exception propagates
# ---------------------------------------------------------------------------

class TestER1YfinanceRaises:
    def test_news_raises_returns_error_dict(self, monkeypatch):
        import src.catalyst.news as mod
        _clear_caches()
        monkeypatch.setattr(mod, "_get_ticker", lambda t: _raising_ticker())

        from src.catalyst.news import get_symbol_news
        result = get_symbol_news("INFY")

        assert "error" in result
        assert result["count"] == 0
        assert result["headlines"] == []

    def test_earnings_raises_returns_error_dict(self, monkeypatch):
        import src.catalyst.earnings as mod
        _clear_caches()
        monkeypatch.setattr(mod, "_get_ticker", lambda t: _raising_ticker())

        from src.catalyst.earnings import get_earnings_calendar
        result = get_earnings_calendar("INFY")

        assert "error" in result
        assert result["next_earnings_date"] is None

    def test_event_risk_survives_all_component_failures(self, monkeypatch):
        import src.catalyst.news as nm
        import src.catalyst.earnings as em
        _clear_caches()
        monkeypatch.setattr(nm, "_get_ticker", lambda t: _raising_ticker())
        monkeypatch.setattr(em, "_get_ticker", lambda t: _raising_ticker())
        monkeypatch.setattr(
            "src.intelligence.risk.get_market_risk_score",
            lambda sym: {"score": 50, "rating": "MODERATE"},
        )

        from src.catalyst.event_risk import get_event_risk
        # Must not raise
        result = get_event_risk("INFY")
        assert "event_risk_score" in result
        assert "error" not in result

    def test_no_exception_propagates_from_news(self, monkeypatch):
        import src.catalyst.news as mod
        _clear_caches()
        monkeypatch.setattr(mod, "_get_ticker", lambda t: _raising_ticker())
        from src.catalyst.news import get_symbol_news
        # Must not raise
        get_symbol_news("TCS")

    def test_no_exception_propagates_from_earnings(self, monkeypatch):
        import src.catalyst.earnings as mod
        _clear_caches()
        monkeypatch.setattr(mod, "_get_ticker", lambda t: _raising_ticker())
        from src.catalyst.earnings import get_earnings_calendar
        # Must not raise
        get_earnings_calendar("RELIANCE")


# ---------------------------------------------------------------------------
# ER-2: Empty news list → valid structured response
# ---------------------------------------------------------------------------

class TestER2EmptyNewsList:
    def test_empty_news_returns_valid_structure(self, monkeypatch):
        import src.catalyst.news as mod
        _clear_caches()
        monkeypatch.setattr(mod, "_get_ticker", lambda t: _empty_ticker())

        from src.catalyst.news import get_symbol_news
        result = get_symbol_news("INFY")

        assert "error" not in result
        assert result["count"] == 0
        assert result["headlines"] == []
        assert "symbol" in result
        assert "yf_ticker" in result

    def test_news_sentiment_with_empty_news_is_neutral(self, monkeypatch):
        import src.catalyst.news as mod
        _clear_caches()
        monkeypatch.setattr(mod, "_get_ticker", lambda t: _empty_ticker())

        from src.catalyst.news import _aggregate_sentiment, get_symbol_news
        news = get_symbol_news("INFY")
        agg = _aggregate_sentiment(news.get("headlines", []))

        assert agg["sentiment"] == "NEUTRAL"
        assert agg["total_articles"] == 0
        assert agg["top_positive_headline"] is None
        assert agg["top_negative_headline"] is None

    def test_empty_news_no_crash_in_event_risk(self, monkeypatch):
        import src.catalyst.news as nm
        import src.catalyst.earnings as em
        _clear_caches()
        monkeypatch.setattr(nm, "_get_ticker", lambda t: _empty_ticker())
        monkeypatch.setattr(em, "_get_ticker", lambda t: _empty_ticker())
        monkeypatch.setattr(
            "src.intelligence.risk.get_market_risk_score",
            lambda sym: {"score": 40, "rating": "MODERATE"},
        )

        from src.catalyst.event_risk import get_event_risk
        result = get_event_risk("INFY")
        assert "error" not in result
        assert 0 <= result["event_risk_score"] <= 100


# ---------------------------------------------------------------------------
# ER-3: Ticker.calendar returns None → null earnings date in response
# ---------------------------------------------------------------------------

class TestER3NoCalendarData:
    def test_null_calendar_yields_null_date(self, monkeypatch):
        import src.catalyst.earnings as mod
        _clear_caches()
        monkeypatch.setattr(mod, "_get_ticker", lambda t: _empty_ticker())

        from src.catalyst.earnings import get_earnings_calendar
        result = get_earnings_calendar("INFY")

        assert "error" not in result
        assert result["next_earnings_date"] is None
        assert result["days_until_earnings"] is None

    def test_null_calendar_proximity_risk_is_low(self, monkeypatch):
        import src.catalyst.earnings as mod
        _clear_caches()
        monkeypatch.setattr(mod, "_get_ticker", lambda t: _empty_ticker())

        from src.catalyst.earnings import get_earnings_calendar
        result = get_earnings_calendar("INFY")

        assert result["earnings_proximity_risk"] == "LOW"
        assert result["earnings_proximity_score"] == 10

    def test_null_calendar_response_has_all_keys(self, monkeypatch):
        import src.catalyst.earnings as mod
        _clear_caches()
        monkeypatch.setattr(mod, "_get_ticker", lambda t: _empty_ticker())

        from src.catalyst.earnings import get_earnings_calendar
        result = get_earnings_calendar("INFY")

        for key in (
            "symbol", "yf_ticker", "next_earnings_date", "days_until_earnings",
            "earnings_proximity_risk", "earnings_proximity_score",
            "upcoming_dividends", "upcoming_splits", "corporate_action_risk",
        ):
            assert key in result, f"missing key: {key}"


# ---------------------------------------------------------------------------
# ER-4: News + earnings both fail → event_risk returns valid response,
#        falls back to market risk only, confidence=0.5
# ---------------------------------------------------------------------------

class TestER4AllFetchesFail:
    def _setup(self, monkeypatch):
        import src.catalyst.news as nm
        import src.catalyst.earnings as em
        _clear_caches()
        monkeypatch.setattr(nm, "_get_ticker", lambda t: _raising_ticker())
        monkeypatch.setattr(em, "_get_ticker", lambda t: _raising_ticker())
        monkeypatch.setattr(
            "src.intelligence.risk.get_market_risk_score",
            lambda sym: {"score": 55, "rating": "MODERATE"},
        )

    def test_event_risk_valid_when_all_fetch_fails(self, monkeypatch):
        self._setup(monkeypatch)
        from src.catalyst.event_risk import get_event_risk
        result = get_event_risk("INFY")
        assert "error" not in result
        assert "event_risk_score" in result

    def test_confidence_is_0_5_market_only(self, monkeypatch):
        self._setup(monkeypatch)
        from src.catalyst.event_risk import get_event_risk
        result = get_event_risk("INFY")
        assert result["confidence"] == 0.5

    def test_score_still_in_range(self, monkeypatch):
        self._setup(monkeypatch)
        from src.catalyst.event_risk import get_event_risk
        result = get_event_risk("INFY")
        assert 0 <= result["event_risk_score"] <= 100

    def test_components_keys_present(self, monkeypatch):
        self._setup(monkeypatch)
        from src.catalyst.event_risk import get_event_risk
        result = get_event_risk("INFY")
        assert "earnings_proximity_score" in result["components"]
        assert "news_sentiment_score" in result["components"]
        assert "market_risk_score" in result["components"]

    def test_nearest_catalyst_null_when_earnings_unavailable(self, monkeypatch):
        self._setup(monkeypatch)
        from src.catalyst.event_risk import get_event_risk
        result = get_event_risk("INFY")
        assert result["nearest_catalyst"] is None
        assert result["highest_impact_catalyst"] is None


# ---------------------------------------------------------------------------
# ER-5: Symbol normalisation is idempotent — INFY, NSE:INFY, INFY.NS all → INFY.NS
# ---------------------------------------------------------------------------

class TestER5SymbolNormalization:
    def _resolve(self, sym):
        from src.catalyst.constants import _to_yf_ticker
        return _to_yf_ticker(sym)

    def test_bare_resolves(self):
        assert self._resolve("INFY") == "INFY.NS"

    def test_prefixed_resolves(self):
        assert self._resolve("NSE:INFY") == "INFY.NS"

    def test_suffixed_is_idempotent(self):
        assert self._resolve("INFY.NS") == "INFY.NS"

    def test_double_call_idempotent(self):
        r1 = self._resolve("INFY")
        r2 = self._resolve(r1)  # apply again to output
        assert r1 == r2 == "INFY.NS"

    def test_bse_prefix_gives_ns_suffix(self):
        # BSE: prefix is stripped; we default to .NS since we don't know BSE intent
        assert self._resolve("BSE:RELIANCE") == "RELIANCE.NS"

    def test_all_three_produce_same_yf_ticker(self, monkeypatch):
        import src.catalyst.news as mod
        with mod._LOCK:
            mod._CACHE.clear()

        seen_tickers = set()

        def capturing_ticker(yf_t):
            seen_tickers.add(yf_t)
            class _T:
                news = []
            return _T()

        monkeypatch.setattr(mod, "_get_ticker", capturing_ticker)

        from src.catalyst.news import get_symbol_news
        get_symbol_news("INFY")
        with mod._LOCK:
            mod._CACHE.clear()
        get_symbol_news("NSE:INFY")
        with mod._LOCK:
            mod._CACHE.clear()
        get_symbol_news("INFY.NS")

        # All three must resolve to the same yfinance ticker
        assert len(seen_tickers) == 1
        assert "INFY.NS" in seen_tickers

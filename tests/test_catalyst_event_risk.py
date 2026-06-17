"""Tests for src/catalyst/event_risk.py"""
from __future__ import annotations

from datetime import date, timedelta


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _future_date(days: int) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


def _clear_cache():
    import src.catalyst.event_risk as mod
    with mod._LOCK:
        mod._CACHE.clear()


def _earnings_result(days=None, prox_risk="LOW", prox_score=10,
                     dividends=None, splits=None, error=None):
    r = {
        "next_earnings_date":      _future_date(days) if days is not None else None,
        "days_until_earnings":     days,
        "earnings_proximity_risk": prox_risk,
        "earnings_proximity_score": prox_score,
        "upcoming_dividends":      dividends or [],
        "upcoming_splits":         splits or [],
    }
    if error:
        r["error"] = error
    return r


def _news_result(headlines=None, error=None):
    r = {"headlines": headlines or []}
    if error:
        r["error"] = error
    return r


# ---------------------------------------------------------------------------
# TestNewsSentimentScore
# ---------------------------------------------------------------------------

class TestNewsSentimentScore:
    def _score(self, sent_score, total):
        from src.catalyst.event_risk import _news_risk_score
        score, desc = _news_risk_score(sent_score, total)
        return score, desc

    def test_very_positive(self):
        score, desc = self._score(0.5, 5)
        assert score == 10

    def test_positive(self):
        score, desc = self._score(0.2, 5)
        assert score == 25

    def test_neutral(self):
        score, desc = self._score(0.0, 5)
        assert score == 45

    def test_negative(self):
        score, desc = self._score(-0.2, 5)
        assert score == 65

    def test_very_negative(self):
        score, desc = self._score(-0.5, 5)
        assert score == 90

    def test_no_articles_returns_neutral(self):
        score, desc = self._score(0.0, 0)
        assert score == 45
        assert "neutral" in desc.lower() or "no articles" in desc.lower()

    def test_description_includes_score(self):
        _, desc = self._score(0.4, 3)
        assert "+0.40" in desc or "VERY_POSITIVE" in desc


# ---------------------------------------------------------------------------
# TestConfidenceModel
# ---------------------------------------------------------------------------

class TestConfidenceModel:
    def _conf(self, news_ok, earnings_ok, market_ok):
        from src.catalyst.event_risk import _confidence
        return _confidence(news_ok, earnings_ok, market_ok)

    def test_all_three_sources(self):
        assert self._conf(True, True, True) == 1.0

    def test_news_and_market(self):
        assert self._conf(True, False, True) == 0.8

    def test_earnings_and_market(self):
        assert self._conf(False, True, True) == 0.8

    def test_news_and_earnings_without_market(self):
        # 2 sources but no market → 0.8 (two-source path)
        assert self._conf(True, True, False) == 0.8

    def test_market_only(self):
        assert self._conf(False, False, True) == 0.5

    def test_no_sources(self):
        assert self._conf(False, False, False) == 0.3

    def test_news_only_without_market(self):
        # 1 source, no market → 0.3
        assert self._conf(True, False, False) == 0.3


# ---------------------------------------------------------------------------
# TestBuildCatalysts
# ---------------------------------------------------------------------------

class TestBuildCatalysts:
    def _nearest(self, earnings_result):
        from src.catalyst.event_risk import _nearest_catalyst, _all_catalysts
        return _nearest_catalyst(_all_catalysts(earnings_result))

    def _highest(self, earnings_result):
        from src.catalyst.event_risk import _highest_impact_catalyst, _all_catalysts
        return _highest_impact_catalyst(_all_catalysts(earnings_result))

    def test_nearest_when_only_earnings(self):
        er = _earnings_result(days=20, prox_risk="LOW", prox_score=10)
        cat = self._nearest(er)
        assert cat is not None
        assert cat["type"] == "EARNINGS"
        assert cat["days_until"] == 20

    def test_nearest_is_dividend_when_sooner(self):
        # Earnings in 20 days, dividend in 5 days
        er = _earnings_result(
            days=20, prox_risk="LOW", prox_score=10,
            dividends=[{"ex_date": _future_date(5), "amount": 10.0,
                        "days_until": 5, "type": "DIVIDEND"}],
        )
        cat = self._nearest(er)
        assert cat is not None
        assert cat["type"] == "DIVIDEND"
        assert cat["days_until"] == 5

    def test_highest_is_earnings_over_dividend(self):
        # Both in range — earnings has priority 100, dividend 40
        er = _earnings_result(
            days=20, prox_risk="LOW", prox_score=10,
            dividends=[{"ex_date": _future_date(5), "amount": 10.0,
                        "days_until": 5, "type": "DIVIDEND"}],
        )
        cat = self._highest(er)
        assert cat is not None
        assert cat["type"] == "EARNINGS"

    def test_split_priority_over_dividend(self):
        # Split priority 70 vs dividend priority 40
        er = _earnings_result(
            dividends=[{"ex_date": _future_date(5), "amount": 10.0,
                        "days_until": 5, "type": "DIVIDEND"}],
            splits=[{"ex_date": _future_date(8), "ratio": 2.0,
                     "days_until": 8, "type": "SPLIT"}],
        )
        cat = self._highest(er)
        assert cat["type"] == "SPLIT"

    def test_none_when_no_catalysts_in_range(self):
        er = _earnings_result(days=None)
        cat = self._nearest(er)
        assert cat is None

    def test_beyond_30_day_horizon_excluded(self):
        # Earnings 45 days away → outside _CATALYST_HORIZON
        er = _earnings_result(days=45, prox_risk="LOW", prox_score=10)
        cat = self._nearest(er)
        assert cat is None


# ---------------------------------------------------------------------------
# TestGetEventRisk — public API
# ---------------------------------------------------------------------------

class TestGetEventRisk:
    def _setup(self, monkeypatch, earnings_days=30, news_score=0.2,
               news_articles=5, market_score=50, earnings_error=False,
               news_error=False, market_error=False):
        import src.catalyst.event_risk as mod
        _clear_cache()

        # Patch earnings
        if earnings_error:
            monkeypatch.setattr(
                "src.catalyst.earnings.get_earnings_calendar",
                lambda sym: {"error": "earnings down"},
            )
        else:
            er = _earnings_result(
                days=earnings_days,
                prox_risk="LOW" if earnings_days > 14 else "HIGH",
                prox_score=10 if earnings_days > 14 else 60,
            )
            monkeypatch.setattr(
                "src.catalyst.earnings.get_earnings_calendar",
                lambda sym: er,
            )

        # Patch news
        if news_error:
            monkeypatch.setattr(
                "src.catalyst.news.get_symbol_news",
                lambda sym, count=10: {"error": "news down"},
            )
        else:
            headlines = [
                {"title": "Beat", "sentiment": "POSITIVE"}
                for _ in range(news_articles)
            ]
            monkeypatch.setattr(
                "src.catalyst.news.get_symbol_news",
                lambda sym, count=10: {"headlines": headlines},
            )

        # Patch market risk (Phase 10)
        if market_error:
            monkeypatch.setattr(
                "src.intelligence.risk.get_market_risk_score",
                lambda sym: {"error": "market risk down"},
            )
        else:
            monkeypatch.setattr(
                "src.intelligence.risk.get_market_risk_score",
                lambda sym: {"score": market_score, "rating": "MODERATE"},
            )

    def test_returns_expected_keys(self, monkeypatch):
        self._setup(monkeypatch)
        from src.catalyst.event_risk import get_event_risk
        result = get_event_risk("INFY")
        for key in (
            "symbol", "event_risk_score", "event_risk_rating", "confidence",
            "components", "factors", "nearest_catalyst",
            "highest_impact_catalyst", "recommendation",
        ):
            assert key in result, f"missing key: {key}"

    def test_score_in_valid_range(self, monkeypatch):
        self._setup(monkeypatch)
        from src.catalyst.event_risk import get_event_risk
        result = get_event_risk("INFY")
        assert 0 <= result["event_risk_score"] <= 100

    def test_rating_valid_values(self, monkeypatch):
        self._setup(monkeypatch)
        from src.catalyst.event_risk import get_event_risk
        result = get_event_risk("INFY")
        assert result["event_risk_rating"] in ("LOW", "MODERATE", "HIGH", "EXTREME")

    def test_confidence_present_and_valid(self, monkeypatch):
        self._setup(monkeypatch)
        from src.catalyst.event_risk import get_event_risk
        result = get_event_risk("INFY")
        assert isinstance(result["confidence"], float)
        assert 0.0 < result["confidence"] <= 1.0

    def test_all_three_sources_confidence_1(self, monkeypatch):
        self._setup(monkeypatch)
        from src.catalyst.event_risk import get_event_risk
        result = get_event_risk("INFY")
        assert result["confidence"] == 1.0

    def test_components_has_weights(self, monkeypatch):
        self._setup(monkeypatch)
        from src.catalyst.event_risk import get_event_risk
        result = get_event_risk("INFY")
        weights = result["components"]["weights"]
        assert weights["earnings"] == 0.40
        assert weights["news"] == 0.30
        assert weights["market"] == 0.30

    def test_factors_list_has_three_items(self, monkeypatch):
        self._setup(monkeypatch)
        from src.catalyst.event_risk import get_event_risk
        result = get_event_risk("INFY")
        assert len(result["factors"]) == 3

    def test_nearest_catalyst_key_present(self, monkeypatch):
        self._setup(monkeypatch, earnings_days=10)
        from src.catalyst.event_risk import get_event_risk
        result = get_event_risk("INFY")
        # Within 30-day horizon — should not be None
        assert result["nearest_catalyst"] is not None
        assert result["nearest_catalyst"]["type"] == "EARNINGS"

    def test_highest_impact_catalyst_key_present(self, monkeypatch):
        self._setup(monkeypatch, earnings_days=10)
        from src.catalyst.event_risk import get_event_risk
        result = get_event_risk("INFY")
        assert result["highest_impact_catalyst"] is not None

    def test_recommendation_is_string(self, monkeypatch):
        self._setup(monkeypatch)
        from src.catalyst.event_risk import get_event_risk
        result = get_event_risk("INFY")
        assert isinstance(result["recommendation"], str)
        assert len(result["recommendation"]) > 0

    def test_composite_score_formula(self, monkeypatch):
        # earnings_score=10 (30 days away, LOW), news all-positive → score=10,
        # market_score=50
        # expected = round(10*0.40 + 10*0.30 + 50*0.30) = round(4+3+15) = 22
        self._setup(monkeypatch, earnings_days=30, news_score=1.0,
                    news_articles=5, market_score=50)
        from src.catalyst.event_risk import get_event_risk
        result = get_event_risk("INFY")
        assert result["event_risk_score"] == 22

    def test_market_only_confidence_when_others_fail(self, monkeypatch):
        self._setup(monkeypatch, news_error=True, earnings_error=True)
        from src.catalyst.event_risk import get_event_risk
        result = get_event_risk("INFY")
        assert result["confidence"] == 0.5

    def test_cache_returns_same_object(self, monkeypatch):
        self._setup(monkeypatch)
        import src.catalyst.event_risk as mod
        _clear_cache()
        from src.catalyst.event_risk import get_event_risk
        r1 = get_event_risk("INFY")
        r2 = get_event_risk("INFY")
        assert r1 is r2

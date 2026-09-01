"""Tests for src/catalyst/earnings.py"""
from __future__ import annotations

import types
from datetime import date, timedelta

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _future_date(days: int) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


def _past_date(days: int) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


class _MockTimestamp:
    """Minimal pandas Timestamp stand-in for ex-date iteration."""
    def __init__(self, d: date):
        self._date = d

    def date(self):
        return self._date


class _MockActionsRow(dict):
    pass


class _MockActions:
    """Minimal pandas DataFrame stand-in with iterrows()."""
    def __init__(self, rows):
        # rows: list of (date, dividends, splits)
        self._rows = rows
        self.empty = len(rows) == 0

    def iterrows(self):
        for d, div, split in self._rows:
            row = {"Dividends": div, "Stock Splits": split}
            yield _MockTimestamp(d), row


class _MockCalendarDF:
    """Minimal DataFrame for .calendar property."""
    def __init__(self, data: dict):
        self._data = data  # {col: [val]}

    @property
    def columns(self):
        return list(self._data.keys())

    def __getitem__(self, col):
        vals = self._data.get(col, [])
        return _DropnaList(vals)


class _DropnaList(list):
    def dropna(self):
        return _DropnaList(v for v in self if v is not None)

    def tolist(self):
        return list(self)


def _mock_ticker(
    calendar=None,
    actions=None,
    raises=False,
):
    class _Ticker:
        @property
        def calendar(self):
            if raises:
                raise RuntimeError("yfinance unavailable")
            return calendar

        @property
        def actions(self):
            if raises:
                raise RuntimeError("yfinance unavailable")
            return actions if actions is not None else _MockActions([])

    return _Ticker()


def _clear_cache():
    import src.catalyst.earnings as mod
    with mod._LOCK:
        mod._CACHE.clear()


# ---------------------------------------------------------------------------
# TestEarningsProximity
# ---------------------------------------------------------------------------

class TestEarningsProximity:
    def _prox(self, days):
        from src.catalyst.earnings import _earnings_proximity
        return _earnings_proximity(days)

    def test_none_returns_low(self):
        label, score = self._prox(None)
        assert label == "LOW"
        assert score == 10

    def test_one_day_imminent(self):
        label, score = self._prox(1)
        assert label == "IMMINENT"
        assert score == 100

    def test_zero_days_imminent(self):
        label, score = self._prox(0)
        assert label == "IMMINENT"
        assert score == 100

    def test_three_days_very_high(self):
        label, score = self._prox(3)
        assert label == "VERY_HIGH"
        assert score == 80

    def test_seven_days_high(self):
        label, score = self._prox(7)
        assert label == "HIGH"
        assert score == 60

    def test_fourteen_days_medium(self):
        label, score = self._prox(14)
        assert label == "MEDIUM"
        assert score == 30

    def test_fifteen_days_low(self):
        label, score = self._prox(15)
        assert label == "LOW"
        assert score == 10

    def test_far_future_low(self):
        label, score = self._prox(60)
        assert label == "LOW"
        assert score == 10


# ---------------------------------------------------------------------------
# TestParseCalendar
# ---------------------------------------------------------------------------

class TestParseCalendar:
    def _parse(self, ticker):
        from src.catalyst.earnings import _parse_calendar
        return _parse_calendar(ticker.calendar)

    def test_none_calendar_returns_nones(self):
        ticker = _mock_ticker(calendar=None)
        d, eps, rev = self._parse(ticker)
        assert d is None
        assert eps is None
        assert rev is None

    def test_valid_calendar_extracts_date(self):
        cal = _MockCalendarDF({
            "Earnings Date": [_future_date(30)],
            "Earnings Average": [18.5],
            "Revenue Average": [38500000000.0],
        })
        ticker = _mock_ticker(calendar=cal)
        d, eps, rev = self._parse(ticker)
        assert d == _future_date(30)
        assert eps == 18.5
        assert rev == 38500000000.0

    def test_missing_earnings_date_col_returns_none(self):
        cal = _MockCalendarDF({"Earnings Average": [18.5]})
        ticker = _mock_ticker(calendar=cal)
        d, eps, rev = self._parse(ticker)
        assert d is None

    def test_eps_none_when_not_available(self):
        cal = _MockCalendarDF({
            "Earnings Date": [_future_date(30)],
        })
        ticker = _mock_ticker(calendar=cal)
        d, eps, rev = self._parse(ticker)
        assert eps is None
        assert rev is None

    def test_dict_calendar_supported(self):
        cal = {
            "Earnings Date": _future_date(30),
            "Earnings Average": 20.0,
            "Revenue Average": None,
        }
        ticker = _mock_ticker(calendar=cal)
        d, eps, rev = self._parse(ticker)
        assert d == _future_date(30)
        assert eps == 20.0
        assert rev is None


# ---------------------------------------------------------------------------
# TestParseActions
# ---------------------------------------------------------------------------

class TestParseActions:
    def _parse(self, ticker, days_ahead=30):
        from src.catalyst.earnings import _parse_actions
        return _parse_actions(ticker.actions, days_ahead)

    def test_empty_actions_returns_empty_lists(self):
        ticker = _mock_ticker(actions=_MockActions([]))
        divs, splits = self._parse(ticker)
        assert divs == []
        assert splits == []

    def test_upcoming_dividend_included(self):
        ex_date = date.today() + timedelta(days=10)
        actions = _MockActions([(ex_date, 21.0, 0)])
        ticker = _mock_ticker(actions=actions)
        divs, splits = self._parse(ticker)
        assert len(divs) == 1
        assert divs[0]["amount"] == 21.0
        assert divs[0]["days_until"] == 10
        assert divs[0]["type"] == "DIVIDEND"

    def test_past_dividend_excluded(self):
        ex_date = date.today() - timedelta(days=5)
        actions = _MockActions([(ex_date, 21.0, 0)])
        ticker = _mock_ticker(actions=actions)
        divs, splits = self._parse(ticker)
        assert divs == []

    def test_upcoming_split_included(self):
        ex_date = date.today() + timedelta(days=7)
        actions = _MockActions([(ex_date, 0, 2.0)])
        ticker = _mock_ticker(actions=actions)
        divs, splits = self._parse(ticker)
        assert len(splits) == 1
        assert splits[0]["ratio"] == 2.0
        assert splits[0]["type"] == "SPLIT"

    def test_beyond_horizon_excluded(self):
        ex_date = date.today() + timedelta(days=60)
        actions = _MockActions([(ex_date, 15.0, 0)])
        ticker = _mock_ticker(actions=actions)
        divs, splits = self._parse(ticker, days_ahead=30)
        assert divs == []

    def test_both_dividend_and_split_same_row(self):
        ex_date = date.today() + timedelta(days=5)
        actions = _MockActions([(ex_date, 10.0, 2.0)])
        ticker = _mock_ticker(actions=actions)
        divs, splits = self._parse(ticker)
        assert len(divs) == 1
        assert len(splits) == 1


# ---------------------------------------------------------------------------
# TestGetEarningsCalendar — public API
# ---------------------------------------------------------------------------

class TestGetEarningsCalendar:
    def _call(self, symbol="INFY", monkeypatch=None, ticker=None):
        import src.catalyst.earnings as mod
        _clear_cache()
        if monkeypatch and ticker is not None:
            monkeypatch.setattr(mod, "_get_ticker", lambda t: ticker)
        from src.catalyst.earnings import get_earnings_calendar
        return get_earnings_calendar(symbol)

    def test_returns_expected_keys(self, monkeypatch):
        cal = _MockCalendarDF({
            "Earnings Date": [_future_date(30)],
            "Earnings Average": [18.5],
        })
        ticker = _mock_ticker(calendar=cal)
        result = self._call(monkeypatch=monkeypatch, ticker=ticker)
        for key in (
            "symbol", "yf_ticker", "next_earnings_date", "days_until_earnings",
            "earnings_proximity_risk", "earnings_proximity_score",
            "eps_estimate", "revenue_estimate",
            "upcoming_dividends", "upcoming_splits", "corporate_action_risk",
        ):
            assert key in result, f"missing key: {key}"

    def test_index_symbol_returns_na(self, monkeypatch):
        # No ticker call needed — index path returns early
        result = self._call(symbol="NIFTY", monkeypatch=monkeypatch, ticker=_mock_ticker())
        assert result["earnings_proximity_risk"] == "N/A"
        assert result["next_earnings_date"] is None
        assert "note" in result

    def test_past_earnings_date_treated_as_null(self, monkeypatch):
        cal = _MockCalendarDF({
            "Earnings Date": [_past_date(5)],
        })
        ticker = _mock_ticker(calendar=cal)
        result = self._call(monkeypatch=monkeypatch, ticker=ticker)
        assert result["next_earnings_date"] is None
        assert result["days_until_earnings"] is None

    def test_days_until_earnings_computed(self, monkeypatch):
        cal = _MockCalendarDF({
            "Earnings Date": [_future_date(20)],
        })
        ticker = _mock_ticker(calendar=cal)
        result = self._call(monkeypatch=monkeypatch, ticker=ticker)
        assert result["days_until_earnings"] == 20

    def test_upcoming_dividends_list(self, monkeypatch):
        ex_date = date.today() + timedelta(days=10)
        cal = _MockCalendarDF({"Earnings Date": [_future_date(30)]})
        actions = _MockActions([(ex_date, 21.0, 0)])
        ticker = _mock_ticker(calendar=cal, actions=actions)
        result = self._call(monkeypatch=monkeypatch, ticker=ticker)
        assert len(result["upcoming_dividends"]) == 1
        assert result["upcoming_dividends"][0]["amount"] == 21.0

    def test_upcoming_splits_list(self, monkeypatch):
        ex_date = date.today() + timedelta(days=5)
        cal = _MockCalendarDF({"Earnings Date": [_future_date(30)]})
        actions = _MockActions([(ex_date, 0, 2.0)])
        ticker = _mock_ticker(calendar=cal, actions=actions)
        result = self._call(monkeypatch=monkeypatch, ticker=ticker)
        assert len(result["upcoming_splits"]) == 1

    def test_no_earnings_date_returns_low_proximity(self, monkeypatch):
        ticker = _mock_ticker(calendar=None)
        result = self._call(monkeypatch=monkeypatch, ticker=ticker)
        assert result["earnings_proximity_risk"] == "LOW"
        assert result["earnings_proximity_score"] == 10
        assert result["next_earnings_date"] is None

    def test_symbol_uppercased(self, monkeypatch):
        ticker = _mock_ticker(calendar=None)
        result = self._call(symbol="infy", monkeypatch=monkeypatch, ticker=ticker)
        assert result["symbol"] == "INFY"

    def test_cache_works(self, monkeypatch):
        import src.catalyst.earnings as mod
        cal = _MockCalendarDF({"Earnings Date": [_future_date(15)]})
        ticker = _mock_ticker(calendar=cal)
        monkeypatch.setattr(mod, "_get_ticker", lambda t: ticker)
        _clear_cache()
        from src.catalyst.earnings import get_earnings_calendar
        r1 = get_earnings_calendar("INFY")
        r2 = get_earnings_calendar("INFY")
        assert r1 is r2

    def test_banknifty_returns_na(self, monkeypatch):
        result = self._call(symbol="BANKNIFTY", monkeypatch=monkeypatch, ticker=_mock_ticker())
        assert result["earnings_proximity_risk"] == "N/A"
        assert result["corporate_action_risk"] == "N/A"

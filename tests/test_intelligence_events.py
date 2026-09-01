"""Tests for src/intelligence/events.py"""
from __future__ import annotations

import json
import time
from datetime import date, timedelta
from unittest.mock import patch

# ---------------------------------------------------------------------------
# nearest_high_impact_days
# ---------------------------------------------------------------------------

class TestNearestHighImpactDays:
    def test_returns_none_when_no_events(self):
        from src.intelligence.events import nearest_high_impact_days
        assert nearest_high_impact_days([]) is None

    def test_returns_none_when_no_high_impact(self):
        from src.intelligence.events import nearest_high_impact_days
        events = [
            {"days_until": 2, "impact": "MEDIUM"},
            {"days_until": 5, "impact": "LOW"},
        ]
        assert nearest_high_impact_days(events) is None

    def test_returns_minimum_days(self):
        from src.intelligence.events import nearest_high_impact_days
        events = [
            {"days_until": 5, "impact": "HIGH"},
            {"days_until": 2, "impact": "HIGH"},
            {"days_until": 8, "impact": "HIGH"},
        ]
        assert nearest_high_impact_days(events) == 2

    def test_ignores_non_high(self):
        from src.intelligence.events import nearest_high_impact_days
        events = [
            {"days_until": 1, "impact": "MEDIUM"},
            {"days_until": 3, "impact": "HIGH"},
        ]
        assert nearest_high_impact_days(events) == 3


# ---------------------------------------------------------------------------
# get_upcoming_events — basic output structure
# ---------------------------------------------------------------------------

class TestGetUpcomingEventsStructure:
    def test_returns_expected_keys(self):
        import src.intelligence.events as ev_mod
        with ev_mod._LOCK:
            ev_mod._CACHE.clear()

        result = ev_mod.get_upcoming_events(days_ahead=365)
        for key in ("days_ahead", "count", "events", "nearest_high_impact_days"):
            assert key in result, f"missing key: {key}"

    def test_count_matches_events_list_length(self):
        import src.intelligence.events as ev_mod
        with ev_mod._LOCK:
            ev_mod._CACHE.clear()

        result = ev_mod.get_upcoming_events(days_ahead=365)
        assert result["count"] == len(result["events"])

    def test_events_sorted_by_date(self):
        import src.intelligence.events as ev_mod
        with ev_mod._LOCK:
            ev_mod._CACHE.clear()

        result = ev_mod.get_upcoming_events(days_ahead=365)
        dates = [e["date"] for e in result["events"]]
        assert dates == sorted(dates)

    def test_no_events_before_today(self):
        import src.intelligence.events as ev_mod
        with ev_mod._LOCK:
            ev_mod._CACHE.clear()

        result = ev_mod.get_upcoming_events(days_ahead=7)
        today_str = date.today().isoformat()
        for e in result["events"]:
            assert e["date"] >= today_str

    def test_events_within_horizon(self):
        import src.intelligence.events as ev_mod
        with ev_mod._LOCK:
            ev_mod._CACHE.clear()

        days = 30
        result = ev_mod.get_upcoming_events(days_ahead=days)
        for e in result["events"]:
            assert 0 <= e["days_until"] <= days


# ---------------------------------------------------------------------------
# env-var override
# ---------------------------------------------------------------------------

class TestEnvVarOverride:
    def test_env_var_events_included(self, monkeypatch):
        import src.intelligence.events as ev_mod
        with ev_mod._LOCK:
            ev_mod._CACHE.clear()

        future_date = (date.today() + timedelta(days=3)).isoformat()
        override = json.dumps([{
            "date": future_date,
            "event_type": "CUSTOM_TEST",
            "description": "Test event",
            "impact": "HIGH",
        }])
        monkeypatch.setenv("UPCOMING_EVENTS_JSON", override)

        result = ev_mod.get_upcoming_events(days_ahead=7)
        event_types = [e["event_type"] for e in result["events"]]
        assert "CUSTOM_TEST" in event_types

    def test_malformed_env_var_ignored(self, monkeypatch):
        import src.intelligence.events as ev_mod
        with ev_mod._LOCK:
            ev_mod._CACHE.clear()

        monkeypatch.setenv("UPCOMING_EVENTS_JSON", "not-valid-json{{{")
        # Should not raise — just returns static events
        result = ev_mod.get_upcoming_events(days_ahead=365)
        assert "events" in result

    def test_empty_env_var_ignored(self, monkeypatch):
        import src.intelligence.events as ev_mod
        with ev_mod._LOCK:
            ev_mod._CACHE.clear()

        monkeypatch.setenv("UPCOMING_EVENTS_JSON", "")
        result = ev_mod.get_upcoming_events(days_ahead=365)
        assert "events" in result


# ---------------------------------------------------------------------------
# Schedule expiry warning
# ---------------------------------------------------------------------------

class TestScheduleExpiryWarning:
    def test_warning_logged_near_expiry(self, monkeypatch, caplog):
        import logging

        import src.intelligence.events as ev_mod
        with ev_mod._LOCK:
            ev_mod._CACHE.clear()

        # Override SCHEDULE_VALID_UNTIL to 10 days from now (within 30-day window)
        near_expiry = date.today() + timedelta(days=10)
        monkeypatch.setattr(ev_mod, "SCHEDULE_VALID_UNTIL", near_expiry)

        with caplog.at_level(logging.WARNING, logger="src.intelligence.events"):
            ev_mod.get_upcoming_events(days_ahead=1)

        assert any("expires" in r.message.lower() for r in caplog.records)


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------

class TestEventsCaching:
    def test_cache_hit_skips_recompute(self):
        import src.intelligence.events as ev_mod
        with ev_mod._LOCK:
            ev_mod._CACHE.clear()

        # First call populates cache
        r1 = ev_mod.get_upcoming_events(days_ahead=7)
        # Inject stale result manually but with fresh timestamp
        with ev_mod._LOCK:
            ev_mod._CACHE["events_7"] = ({"cached": True}, time.monotonic())

        r2 = ev_mod.get_upcoming_events(days_ahead=7)
        assert r2 == {"cached": True}

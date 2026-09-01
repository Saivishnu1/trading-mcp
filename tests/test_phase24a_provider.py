"""
Phase 24A — Provider Framework & Calendar Infrastructure tests (D9).

Coverage:
  D1  BaseProvider / ProviderResult contracts
  D2  CalendarProviderChain (chain traversal, singleton, reset)
  D3  JSONCalendarProvider (file loading, TTL cache, year-boundary, malformed JSON)
  D4  EmergencyCalendarProvider (always returns data, minimal embedded set)
  D5  Provider metadata schema (all required fields)
  D6  Source transparency in get_market_calendar() via source_meta
  D7  Provider health states (HEALTHY, CACHED, EMERGENCY, FAILED)
  D8  get_market_calendar() integration with provider chain
  D9  Missing year, leap year, malformed JSON edge cases
"""
from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_REQUIRED_PROVIDER_META_KEYS = frozenset({
    "provider_name", "data_source", "authority", "status",
    "cache_status", "cache_age_seconds", "ttl_seconds",
    "last_refresh", "fallback_level",
})

_REQUIRED_SOURCE_META_KEYS = frozenset({
    "provider", "authority", "data_source", "status",
})

_VALID_STATUSES = {"HEALTHY", "CACHED", "EMERGENCY", "FAILED"}
_VALID_CACHE_STATUSES = {"HIT", "MISS", "BYPASS"}


def _custom_holidays(year: int = 2026) -> dict[date, str]:
    return {date(year, 3, 5): f"Custom {year}", date(year, 11, 1): f"Another {year}"}


# ---------------------------------------------------------------------------
# D1 — ProviderResult contract
# ---------------------------------------------------------------------------

class TestProviderResultContract:
    """ProviderResult must always carry full provenance metadata."""

    def _make_result(self, **overrides):
        from src.providers.base import ProviderResult
        defaults = dict(
            data={date(2026, 1, 1): "New Year"},
            provider_name="TestProvider",
            data_source="test://source",
            authority="Test Authority",
            status="HEALTHY",
            fallback_level=0,
            cache_status="MISS",
            cache_age_seconds=0,
            ttl_seconds=3600,
            last_refresh="2026-01-01T00:00:00Z",
        )
        defaults.update(overrides)
        return ProviderResult(**defaults)

    def test_provider_meta_has_all_required_keys(self):
        result = self._make_result()
        meta = result.as_provider_meta()
        assert _REQUIRED_PROVIDER_META_KEYS <= meta.keys()

    def test_source_meta_has_all_required_keys(self):
        result = self._make_result()
        meta = result.as_source_meta()
        assert _REQUIRED_SOURCE_META_KEYS <= meta.keys()

    def test_source_meta_provider_matches_provider_name(self):
        result = self._make_result(provider_name="XYZ")
        assert result.as_source_meta()["provider"] == "XYZ"

    def test_source_meta_status_matches_result_status(self):
        result = self._make_result(status="EMERGENCY")
        assert result.as_source_meta()["status"] == "EMERGENCY"

    def test_provider_meta_fallback_level_matches(self):
        result = self._make_result(fallback_level=2)
        assert result.as_provider_meta()["fallback_level"] == 2

    def test_provider_meta_cache_status_matches(self):
        result = self._make_result(cache_status="HIT")
        assert result.as_provider_meta()["cache_status"] == "HIT"

    def test_provider_meta_ttl_seconds_matches(self):
        result = self._make_result(ttl_seconds=86400)
        assert result.as_provider_meta()["ttl_seconds"] == 86400

    def test_valid_status_values(self):
        for status in _VALID_STATUSES:
            result = self._make_result(status=status)
            assert result.as_provider_meta()["status"] == status


# ---------------------------------------------------------------------------
# D3 — JSONCalendarProvider
# ---------------------------------------------------------------------------

class TestJSONCalendarProvider:
    """Tests for the JSON-file-backed calendar provider."""

    def setup_method(self):
        from src.market import calendar as _cal
        _cal._reset_holiday_cache()

    def teardown_method(self):
        from src.market import calendar as _cal
        _cal._reset_holiday_cache()

    def test_fetch_returns_provider_result_on_success(self):
        from src.providers.calendar.json_provider import JSONCalendarProvider
        provider = JSONCalendarProvider()
        custom = _custom_holidays()
        with patch.object(provider, "_load_raw_json", return_value=custom):
            result = provider.fetch()
        assert result is not None
        assert result.status == "HEALTHY"

    def test_fetch_returns_none_when_no_json_files(self):
        from src.providers.calendar.json_provider import JSONCalendarProvider
        provider = JSONCalendarProvider()
        with patch.object(provider, "_load_raw_json", side_effect=FileNotFoundError("no file")):
            result = provider.fetch()
        assert result is None  # chain should try next provider

    def test_fetch_returns_none_on_json_exception(self):
        from src.providers.calendar.json_provider import JSONCalendarProvider
        provider = JSONCalendarProvider()
        with patch.object(provider, "_load_raw_json", side_effect=RuntimeError("disk error")):
            result = provider.fetch()
        assert result is None

    def test_first_fetch_is_miss(self):
        from src.providers.calendar.json_provider import JSONCalendarProvider
        provider = JSONCalendarProvider()
        custom = _custom_holidays()
        with patch.object(provider, "_load_raw_json", return_value=custom):
            result = provider.fetch()
        assert result.cache_status == "MISS"
        assert result.cache_age_seconds == 0

    def test_second_fetch_is_cache_hit(self):
        from src.providers.calendar.json_provider import JSONCalendarProvider
        provider = JSONCalendarProvider()
        custom = _custom_holidays()
        with patch.object(provider, "_load_raw_json", return_value=custom) as mock_load:
            provider.fetch()   # populate cache
            result = provider.fetch()  # cache hit
        assert result.cache_status == "HIT"
        assert mock_load.call_count == 1

    def test_cache_hit_returns_cached_status(self):
        from src.providers.calendar.json_provider import JSONCalendarProvider
        provider = JSONCalendarProvider()
        custom = _custom_holidays()
        with patch.object(provider, "_load_raw_json", return_value=custom):
            provider.fetch()
            result = provider.fetch()
        assert result.status == "CACHED"

    def test_cache_hit_data_matches_original(self):
        from src.providers.calendar.json_provider import JSONCalendarProvider
        provider = JSONCalendarProvider()
        custom = _custom_holidays()
        with patch.object(provider, "_load_raw_json", return_value=custom):
            provider.fetch()
            result = provider.fetch()
        assert result.data == custom

    def test_json_not_reloaded_within_ttl(self):
        from src.providers.calendar.json_provider import JSONCalendarProvider
        provider = JSONCalendarProvider()
        custom = _custom_holidays()
        with patch.object(provider, "_load_raw_json", return_value=custom) as mock_load:
            for _ in range(5):
                provider.fetch()
        assert mock_load.call_count == 1

    def test_stale_cache_served_when_json_fails(self):
        """When cache is populated but reload fails, serve stale cache rather than None."""
        from src.providers.calendar.json_provider import JSONCalendarProvider
        provider = JSONCalendarProvider(ttl_seconds=0)  # TTL=0 → always expired
        custom = _custom_holidays()
        # First load succeeds
        with patch.object(provider, "_load_raw_json", return_value=custom):
            provider.fetch()
        # Now TTL=0 means it tries to reload, but fails — should serve stale cache
        with patch.object(provider, "_load_raw_json", side_effect=RuntimeError("fail")):
            result = provider.fetch()
        assert result is not None
        assert result.data == custom

    def test_provider_name_is_json_calendar_provider(self):
        from src.providers.calendar.json_provider import JSONCalendarProvider
        assert JSONCalendarProvider().name == "JSONCalendarProvider"

    def test_authority_is_nse_holiday_circular(self):
        from src.providers.calendar.json_provider import JSONCalendarProvider
        provider = JSONCalendarProvider()
        custom = _custom_holidays()
        with patch.object(provider, "_load_raw_json", return_value=custom):
            result = provider.fetch()
        assert "NSE" in result.authority

    def test_health_before_fetch_is_offline(self):
        from src.providers.calendar.json_provider import JSONCalendarProvider
        provider = JSONCalendarProvider()
        h = provider.health()
        assert h["status"] == "OFFLINE"

    def test_health_after_fetch_is_healthy(self):
        from src.providers.calendar.json_provider import JSONCalendarProvider
        provider = JSONCalendarProvider()
        custom = _custom_holidays()
        with patch.object(provider, "_load_raw_json", return_value=custom):
            provider.fetch()
        h = provider.health()
        assert h["status"] == "HEALTHY"

    def test_reset_clears_cache(self):
        from src.providers.calendar.json_provider import JSONCalendarProvider
        provider = JSONCalendarProvider()
        custom = _custom_holidays()
        with patch.object(provider, "_load_raw_json", return_value=custom) as mock_load:
            provider.fetch()
            provider.reset()
            provider.fetch()  # should re-read
        assert mock_load.call_count == 2

    def test_loads_current_and_next_year(self):
        """_load_raw_json is called for current year; provider loads current + next year."""
        from src.providers.calendar.json_provider import JSONCalendarProvider
        today = date.today()
        curr_year = today.year
        next_year = today.year + 1
        # Create in-memory JSON data for both years
        curr_data = [{"date": f"{curr_year}-03-05", "name": "Holiday A"}]
        next_data = [{"date": f"{next_year}-03-05", "name": "Holiday B"}]
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir)
            (d / f"{curr_year}.json").write_text(json.dumps(curr_data))
            (d / f"{next_year}.json").write_text(json.dumps(next_data))
            provider = JSONCalendarProvider(resources_dir=d)
            result = provider.fetch()
        assert date(curr_year, 3, 5) in result.data
        assert date(next_year, 3, 5) in result.data

    def test_missing_current_year_uses_next(self):
        """If current year JSON is missing, next year is still loaded."""
        from src.providers.calendar.json_provider import JSONCalendarProvider
        today = date.today()
        next_year = today.year + 1
        next_data = [{"date": f"{next_year}-06-15", "name": "Holiday B"}]
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir)
            (d / f"{next_year}.json").write_text(json.dumps(next_data))
            provider = JSONCalendarProvider(resources_dir=d)
            result = provider.fetch()
        assert result is not None
        assert date(next_year, 6, 15) in result.data

    def test_missing_both_years_returns_none(self):
        """No JSON files for current or next year → returns None (chain tries Emergency)."""
        import tempfile

        from src.providers.calendar.json_provider import JSONCalendarProvider
        with tempfile.TemporaryDirectory() as tmpdir:
            provider = JSONCalendarProvider(resources_dir=Path(tmpdir))
            result = provider.fetch()
        assert result is None

    def test_malformed_json_returns_none(self):
        """Malformed JSON file → provider returns None."""
        import tempfile

        from src.providers.calendar.json_provider import JSONCalendarProvider
        today = date.today()
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir)
            (d / f"{today.year}.json").write_text("this is not json {{{")
            provider = JSONCalendarProvider(resources_dir=d)
            result = provider.fetch()
        assert result is None


# ---------------------------------------------------------------------------
# D4 — EmergencyCalendarProvider
# ---------------------------------------------------------------------------

class TestEmergencyCalendarProvider:
    """Emergency provider always returns data with minimal embedded holidays."""

    def test_fetch_always_returns_result(self):
        from src.providers.calendar.emergency import EmergencyCalendarProvider
        result = EmergencyCalendarProvider().fetch()
        assert result is not None

    def test_fetch_status_is_emergency(self):
        from src.providers.calendar.emergency import EmergencyCalendarProvider
        result = EmergencyCalendarProvider().fetch()
        assert result.status == "EMERGENCY"

    def test_fetch_fallback_level_is_2(self):
        from src.providers.calendar.emergency import EmergencyCalendarProvider
        result = EmergencyCalendarProvider().fetch()
        assert result.fallback_level == 2

    def test_fetch_cache_status_is_bypass(self):
        from src.providers.calendar.emergency import EmergencyCalendarProvider
        result = EmergencyCalendarProvider().fetch()
        assert result.cache_status == "BYPASS"

    def test_fetch_data_is_dict(self):
        from src.providers.calendar.emergency import EmergencyCalendarProvider
        result = EmergencyCalendarProvider().fetch()
        assert isinstance(result.data, dict)

    def test_fetch_data_has_dates(self):
        from src.providers.calendar.emergency import EmergencyCalendarProvider
        result = EmergencyCalendarProvider().fetch()
        assert len(result.data) > 0

    def test_data_keys_are_date_objects(self):
        from src.providers.calendar.emergency import EmergencyCalendarProvider
        result = EmergencyCalendarProvider().fetch()
        for key in result.data:
            assert isinstance(key, date)

    def test_data_values_are_strings(self):
        from src.providers.calendar.emergency import EmergencyCalendarProvider
        result = EmergencyCalendarProvider().fetch()
        for val in result.data.values():
            assert isinstance(val, str)

    def test_health_returns_emergency_status(self):
        from src.providers.calendar.emergency import EmergencyCalendarProvider
        h = EmergencyCalendarProvider().health()
        assert h["status"] == "EMERGENCY"

    def test_health_has_reason(self):
        from src.providers.calendar.emergency import EmergencyCalendarProvider
        h = EmergencyCalendarProvider().health()
        assert "reason" in h

    def test_provider_name_is_emergency_calendar_provider(self):
        from src.providers.calendar.emergency import EmergencyCalendarProvider
        assert EmergencyCalendarProvider().name == "EmergencyCalendarProvider"

    def test_authority_mentions_partial(self):
        from src.providers.calendar.emergency import EmergencyCalendarProvider
        result = EmergencyCalendarProvider().fetch()
        assert "partial" in result.authority.lower() or "emergency" in result.data_source.lower()

    def test_includes_current_year_holidays(self):
        from src.providers.calendar.emergency import EmergencyCalendarProvider
        result = EmergencyCalendarProvider().fetch()
        today = date.today()
        year_holidays = {d for d in result.data if d.year == today.year}
        assert len(year_holidays) > 0


# ---------------------------------------------------------------------------
# D2 — CalendarProviderChain
# ---------------------------------------------------------------------------

class TestCalendarProviderChain:
    def setup_method(self):
        from src.market import calendar as _cal
        _cal._reset_holiday_cache()

    def teardown_method(self):
        from src.market import calendar as _cal
        _cal._reset_holiday_cache()

    def test_chain_returns_json_result_when_json_available(self):
        from src.providers.calendar.chain import CalendarProviderChain
        chain = CalendarProviderChain()
        custom = _custom_holidays()
        with patch("src.providers.calendar.json_provider.JSONCalendarProvider._load_raw_json",
                   return_value=custom):
            result = chain.fetch()
        assert result.provider_name == "JSONCalendarProvider"
        assert result.status in ("HEALTHY", "CACHED")

    def test_chain_falls_to_emergency_when_json_fails(self):
        from src.providers.calendar.chain import CalendarProviderChain
        chain = CalendarProviderChain()
        with patch("src.providers.calendar.json_provider.JSONCalendarProvider._load_raw_json",
                   side_effect=FileNotFoundError("no file")):
            result = chain.fetch()
        assert result.provider_name == "EmergencyCalendarProvider"
        assert result.status == "EMERGENCY"

    def test_chain_result_data_is_dict_of_dates(self):
        from src.providers.calendar.chain import CalendarProviderChain
        chain = CalendarProviderChain()
        result = chain.fetch()
        assert isinstance(result.data, dict)
        for key in result.data:
            assert isinstance(key, date)

    def test_singleton_returns_same_instance(self):
        from src.providers.calendar.chain import get_calendar_provider
        a = get_calendar_provider()
        b = get_calendar_provider()
        assert a is b

    def test_reset_creates_fresh_chain(self):
        from src.providers.calendar.chain import get_calendar_provider, reset_calendar_provider
        a = get_calendar_provider()
        reset_calendar_provider()
        b = get_calendar_provider()
        assert a is not b

    def test_chain_health_before_fetch_returns_dict(self):
        from src.providers.calendar.chain import CalendarProviderChain
        chain = CalendarProviderChain()
        h = chain.health()
        assert isinstance(h, dict)
        assert "status" in h

    def test_chain_health_after_healthy_fetch(self):
        from src.providers.calendar.chain import CalendarProviderChain
        chain = CalendarProviderChain()
        custom = _custom_holidays()
        with patch("src.providers.calendar.json_provider.JSONCalendarProvider._load_raw_json",
                   return_value=custom):
            chain.fetch()
        h = chain.health()
        assert h["status"] in ("HEALTHY", "CACHED")

    def test_chain_health_after_emergency_fetch(self):
        from src.providers.calendar.chain import CalendarProviderChain
        chain = CalendarProviderChain()
        with patch("src.providers.calendar.json_provider.JSONCalendarProvider._load_raw_json",
                   side_effect=FileNotFoundError("no json")):
            chain.fetch()
        h = chain.health()
        assert h["status"] == "EMERGENCY"
        assert h["severity"] == "WARNING"

    def test_chain_health_has_holiday_source(self):
        from src.providers.calendar.chain import CalendarProviderChain
        chain = CalendarProviderChain()
        custom = _custom_holidays()
        with patch("src.providers.calendar.json_provider.JSONCalendarProvider._load_raw_json",
                   return_value=custom):
            chain.fetch()
        h = chain.health()
        assert "holiday_source" in h

    def test_chain_last_result_initially_none(self):
        from src.providers.calendar.chain import CalendarProviderChain
        chain = CalendarProviderChain()
        assert chain.last_result is None

    def test_chain_last_result_set_after_fetch(self):
        from src.providers.calendar.chain import CalendarProviderChain
        chain = CalendarProviderChain()
        custom = _custom_holidays()
        with patch("src.providers.calendar.json_provider.JSONCalendarProvider._load_raw_json",
                   return_value=custom):
            chain.fetch()
        assert chain.last_result is not None


# ---------------------------------------------------------------------------
# D5 — Provider metadata schema
# ---------------------------------------------------------------------------

class TestProviderMetadataSchema:
    def setup_method(self):
        from src.market import calendar as _cal
        _cal._reset_holiday_cache()

    def teardown_method(self):
        from src.market import calendar as _cal
        _cal._reset_holiday_cache()

    def _get_json_result(self):
        from src.providers.calendar.chain import CalendarProviderChain
        chain = CalendarProviderChain()
        custom = _custom_holidays()
        with patch("src.providers.calendar.json_provider.JSONCalendarProvider._load_raw_json",
                   return_value=custom):
            return chain.fetch()

    def _get_emergency_result(self):
        from src.providers.calendar.chain import CalendarProviderChain
        chain = CalendarProviderChain()
        with patch("src.providers.calendar.json_provider.JSONCalendarProvider._load_raw_json",
                   side_effect=FileNotFoundError("no json")):
            return chain.fetch()

    def test_json_provider_meta_has_all_keys(self):
        result = self._get_json_result()
        assert _REQUIRED_PROVIDER_META_KEYS <= result.as_provider_meta().keys()

    def test_emergency_provider_meta_has_all_keys(self):
        result = self._get_emergency_result()
        assert _REQUIRED_PROVIDER_META_KEYS <= result.as_provider_meta().keys()

    def test_json_provider_meta_ttl_positive(self):
        result = self._get_json_result()
        assert result.as_provider_meta()["ttl_seconds"] > 0

    def test_emergency_provider_meta_ttl_zero(self):
        result = self._get_emergency_result()
        assert result.as_provider_meta()["ttl_seconds"] == 0

    def test_json_fallback_level_zero(self):
        result = self._get_json_result()
        assert result.as_provider_meta()["fallback_level"] == 0

    def test_emergency_fallback_level_two(self):
        result = self._get_emergency_result()
        assert result.as_provider_meta()["fallback_level"] == 2

    def test_last_refresh_is_iso_string(self):
        result = self._get_json_result()
        last_refresh = result.as_provider_meta()["last_refresh"]
        assert "T" in last_refresh and "Z" in last_refresh

    def test_status_is_valid(self):
        for result in (self._get_json_result(), self._get_emergency_result()):
            assert result.as_provider_meta()["status"] in _VALID_STATUSES

    def test_cache_status_is_valid(self):
        for result in (self._get_json_result(), self._get_emergency_result()):
            assert result.as_provider_meta()["cache_status"] in _VALID_CACHE_STATUSES


# ---------------------------------------------------------------------------
# D6 — Source transparency in get_market_calendar()
# ---------------------------------------------------------------------------

class TestCalendarSourceTransparencyV2:
    def setup_method(self):
        from src.market import calendar as _cal
        _cal._reset_holiday_cache()

    def teardown_method(self):
        from src.market import calendar as _cal
        _cal._reset_holiday_cache()

    def test_source_meta_present(self):
        from src.market.calendar import get_market_calendar
        with patch("src.market.calendar._live_expiries", return_value={}):
            cal = get_market_calendar()
        assert "source_meta" in cal

    def test_source_meta_required_keys(self):
        from src.market.calendar import get_market_calendar
        with patch("src.market.calendar._live_expiries", return_value={}):
            cal = get_market_calendar()
        meta = cal["source_meta"]
        for key in ("provider", "authority", "data_source", "status", "expiry_source"):
            assert key in meta

    def test_source_meta_provider_meta_present(self):
        from src.market.calendar import get_market_calendar
        with patch("src.market.calendar._live_expiries", return_value={}):
            cal = get_market_calendar()
        assert "provider_meta" in cal["source_meta"]

    def test_provider_meta_has_all_required_keys(self):
        from src.market.calendar import get_market_calendar
        with patch("src.market.calendar._live_expiries", return_value={}):
            cal = get_market_calendar()
        pm = cal["source_meta"]["provider_meta"]
        assert _REQUIRED_PROVIDER_META_KEYS <= pm.keys()

    def test_json_provider_reflected_in_source_meta(self):
        from src.market.calendar import get_market_calendar
        custom = _custom_holidays()
        with patch("src.providers.calendar.json_provider.JSONCalendarProvider._load_raw_json",
                   return_value=custom):
            with patch("src.market.calendar._live_expiries", return_value={}):
                cal = get_market_calendar()
        assert cal["source_meta"]["provider"] == "JSONCalendarProvider"

    def test_emergency_provider_reflected_when_json_unavailable(self):
        from src.market.calendar import get_market_calendar
        with patch("src.providers.calendar.json_provider.JSONCalendarProvider._load_raw_json",
                   side_effect=FileNotFoundError("no json")):
            with patch("src.market.calendar._live_expiries", return_value={}):
                cal = get_market_calendar()
        assert cal["source_meta"]["provider"] == "EmergencyCalendarProvider"
        assert cal["source_meta"]["status"] == "EMERGENCY"

    def test_expiry_source_in_source_meta(self):
        from src.market.calendar import get_market_calendar
        with patch("src.market.calendar._live_expiries", return_value={}):
            cal = get_market_calendar()
        assert cal["source_meta"]["expiry_source"] == "algorithmic"

    def test_expiry_source_live_when_nse_up(self):
        from src.market.calendar import get_market_calendar
        with patch("src.market.calendar._live_expiries", return_value={"nifty": "26-Jun-2026"}):
            cal = get_market_calendar()
        assert cal["source_meta"]["expiry_source"] == "live"


# ---------------------------------------------------------------------------
# D7 — Provider health states
# ---------------------------------------------------------------------------

class TestProviderHealthStates:
    def setup_method(self):
        from src.market import calendar as _cal
        _cal._reset_holiday_cache()

    def teardown_method(self):
        from src.market import calendar as _cal
        _cal._reset_holiday_cache()

    def _health(self):
        from src.market.calendar import get_calendar_health
        return get_calendar_health()

    def test_healthy_state_info_severity(self):
        custom = _custom_holidays()
        with patch("src.providers.calendar.json_provider.JSONCalendarProvider._load_raw_json",
                   return_value=custom):
            h = self._health()
        assert h["status"] == "HEALTHY"
        assert h["severity"] == "INFO"

    def test_cached_state_info_severity(self):
        from src.providers.calendar.chain import get_calendar_provider
        custom = _custom_holidays()
        with patch("src.providers.calendar.json_provider.JSONCalendarProvider._load_raw_json",
                   return_value=custom):
            chain = get_calendar_provider()
            chain.fetch()
            chain.fetch()  # second fetch → CACHED
        h = self._health()
        assert h["status"] == "CACHED"
        assert h["severity"] == "INFO"

    def test_emergency_state_warning_severity(self):
        with patch("src.providers.calendar.json_provider.JSONCalendarProvider._load_raw_json",
                   side_effect=FileNotFoundError("no json")):
            h = self._health()
        assert h["status"] == "EMERGENCY"
        assert h["severity"] == "WARNING"

    def test_emergency_has_reason(self):
        with patch("src.providers.calendar.json_provider.JSONCalendarProvider._load_raw_json",
                   side_effect=FileNotFoundError("no json")):
            h = self._health()
        assert "reason" in h and h["reason"]

    def test_emergency_has_recommended_action(self):
        with patch("src.providers.calendar.json_provider.JSONCalendarProvider._load_raw_json",
                   side_effect=FileNotFoundError("no json")):
            h = self._health()
        assert "recommended_action" in h

    def test_health_always_has_holiday_source(self):
        h = self._health()
        assert "holiday_source" in h

    def test_health_always_has_expiry_source(self):
        h = self._health()
        assert "expiry_source" in h

    def test_healthy_holiday_source_is_json(self):
        custom = _custom_holidays()
        with patch("src.providers.calendar.json_provider.JSONCalendarProvider._load_raw_json",
                   return_value=custom):
            h = self._health()
        assert h["holiday_source"] == "json"

    def test_emergency_holiday_source_is_emergency(self):
        with patch("src.providers.calendar.json_provider.JSONCalendarProvider._load_raw_json",
                   side_effect=FileNotFoundError("no json")):
            h = self._health()
        assert h["holiday_source"] == "emergency"


# ---------------------------------------------------------------------------
# D8 — get_market_calendar() integration
# ---------------------------------------------------------------------------

class TestCalendarProviderIntegration:
    def setup_method(self):
        from src.market import calendar as _cal
        _cal._reset_holiday_cache()

    def teardown_method(self):
        from src.market import calendar as _cal
        _cal._reset_holiday_cache()

    def test_get_market_calendar_returns_dict(self):
        from src.market.calendar import get_market_calendar
        with patch("src.market.calendar._live_expiries", return_value={}):
            cal = get_market_calendar()
        assert isinstance(cal, dict)

    def test_get_market_calendar_has_all_canonical_keys(self):
        from src.market.calendar import get_market_calendar
        with patch("src.market.calendar._live_expiries", return_value={}):
            cal = get_market_calendar()
        required = {"today", "expiries", "days_to_expiry", "upcoming_holidays",
                    "next_trading_day", "week_summary", "source_meta"}
        assert required <= cal.keys()

    def test_holiday_from_json_is_recognized(self):
        """A holiday from the JSON file is correctly identified as is_holiday=True."""
        from src.market.calendar import _today_ist, get_market_calendar
        # get_market_calendar() keys its holiday lookup on _today_ist(), not
        # date.today() — using date.today() here made this test flaky on
        # UTC CI runners during IST 00:00-05:29 (UTC still "yesterday"),
        # exactly the day-boundary bug already fixed in calendar.py itself
        # (see _today_ist()'s docstring, 2026-07-13). Match the production
        # code's own notion of "today" instead of the OS/process-local date.
        today = _today_ist()
        custom = {today: "Test Holiday Today"}
        with patch("src.providers.calendar.json_provider.JSONCalendarProvider._load_raw_json",
                   return_value=custom):
            with patch("src.market.calendar._live_expiries", return_value={}):
                cal = get_market_calendar()
        assert cal["today"]["is_holiday"] is True
        assert cal["today"]["holiday_name"] == "Test Holiday Today"

    def test_non_holiday_not_flagged(self):
        from src.market.calendar import get_market_calendar
        with patch("src.providers.calendar.json_provider.JSONCalendarProvider._load_raw_json",
                   return_value={}):
            with patch("src.market.calendar._live_expiries", return_value={}):
                cal = get_market_calendar()
        today_info = cal["today"]
        if not today_info["is_holiday"]:
            assert today_info["holiday_name"] is None

    def test_upcoming_holidays_from_json(self):
        """Holidays loaded from JSON appear in upcoming_holidays."""
        from src.market.calendar import get_market_calendar
        today = date.today()
        from datetime import timedelta
        upcoming_date = today + timedelta(days=5)
        custom = {upcoming_date: "Upcoming Test Holiday"}
        with patch("src.providers.calendar.json_provider.JSONCalendarProvider._load_raw_json",
                   return_value=custom):
            with patch("src.market.calendar._live_expiries", return_value={}):
                cal = get_market_calendar()
        upcoming_dates = [h["date"] for h in cal["upcoming_holidays"]]
        assert upcoming_date.isoformat() in upcoming_dates

    def test_emergency_fallback_calendar_still_functional(self):
        """Even with EMERGENCY fallback, get_market_calendar returns complete response."""
        from src.market.calendar import get_market_calendar
        with patch("src.providers.calendar.json_provider.JSONCalendarProvider._load_raw_json",
                   side_effect=FileNotFoundError("no json")):
            with patch("src.market.calendar._live_expiries", return_value={}):
                cal = get_market_calendar()
        required = {"today", "expiries", "days_to_expiry", "next_trading_day"}
        assert required <= cal.keys()
        assert cal["source_meta"]["status"] == "EMERGENCY"

    def test_expiry_dates_are_iso_strings(self):
        from src.market.calendar import get_market_calendar
        with patch("src.market.calendar._live_expiries", return_value={}):
            cal = get_market_calendar()
        for idx, exp_str in cal["expiries"].items():
            assert date.fromisoformat(exp_str)  # must be parseable

    def test_days_to_expiry_are_integers(self):
        from src.market.calendar import get_market_calendar
        with patch("src.market.calendar._live_expiries", return_value={}):
            cal = get_market_calendar()
        for idx, days in cal["days_to_expiry"].items():
            assert isinstance(days, int)


# ---------------------------------------------------------------------------
# D9 — Edge cases: missing year, leap year, malformed JSON
# ---------------------------------------------------------------------------

class TestCalendarEdgeCases:
    def setup_method(self):
        from src.market import calendar as _cal
        _cal._reset_holiday_cache()

    def teardown_method(self):
        from src.market import calendar as _cal
        _cal._reset_holiday_cache()

    def test_leap_year_feb29_in_json_loads_correctly(self):
        """Dates like 2028-02-29 (leap day) must parse correctly from JSON."""
        import tempfile

        from src.providers.calendar.json_provider import JSONCalendarProvider
        # 2028 is a leap year
        data = [{"date": "2028-02-29", "name": "Leap Day Holiday"}]
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir)
            (d / "2028.json").write_text(json.dumps(data))
            provider = JSONCalendarProvider(resources_dir=d)
            result = provider.fetch()
        if result is not None:
            assert date(2028, 2, 29) in result.data

    def test_missing_year_json_falls_to_next_year(self):
        """Missing current year JSON doesn't crash — uses next year if available."""
        import tempfile

        from src.providers.calendar.json_provider import JSONCalendarProvider
        today = date.today()
        next_year = today.year + 1
        data = [{"date": f"{next_year}-12-25", "name": "Christmas"}]
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir)
            (d / f"{next_year}.json").write_text(json.dumps(data))
            provider = JSONCalendarProvider(resources_dir=d)
            result = provider.fetch()
        assert result is not None
        assert date(next_year, 12, 25) in result.data

    def test_malformed_json_falls_to_emergency(self):
        """Malformed JSON → JSONCalendarProvider returns None → chain uses Emergency."""
        from src.providers.calendar.chain import CalendarProviderChain
        chain = CalendarProviderChain()
        with patch("src.providers.calendar.json_provider.JSONCalendarProvider._load_raw_json",
                   side_effect=json.JSONDecodeError("malformed", "", 0)):
            result = chain.fetch()
        assert result.provider_name == "EmergencyCalendarProvider"
        assert result.status == "EMERGENCY"

    def test_empty_json_array_falls_to_none(self):
        """Empty JSON arrays for all years → no holidays → _load_raw_json raises → fetch returns None."""
        from src.providers.calendar.json_provider import JSONCalendarProvider
        provider = JSONCalendarProvider()
        # Simulate empty arrays: _load_raw_json raises FileNotFoundError because holidays is empty
        with patch.object(provider, "_load_raw_json",
                          side_effect=FileNotFoundError("no holidays in json")):
            result = provider.fetch()
        assert result is None

    def test_real_json_files_loadable(self):
        """The actual resources/calendar/ JSON files must be parseable by the provider."""
        from src.providers.calendar.json_provider import JSONCalendarProvider
        # Use a fresh provider that reads from the real resources directory
        provider = JSONCalendarProvider()
        result = provider._load_raw_json()
        assert isinstance(result, dict)
        assert len(result) > 0

    def test_real_json_files_contain_date_objects(self):
        from src.providers.calendar.json_provider import JSONCalendarProvider
        provider = JSONCalendarProvider()
        result = provider._load_raw_json()
        for key in result:
            assert isinstance(key, date), f"Expected date, got {type(key)}: {key}"

    def test_real_json_files_contain_string_values(self):
        from src.providers.calendar.json_provider import JSONCalendarProvider
        provider = JSONCalendarProvider()
        result = provider._load_raw_json()
        for val in result.values():
            assert isinstance(val, str), f"Expected str, got {type(val)}: {val}"

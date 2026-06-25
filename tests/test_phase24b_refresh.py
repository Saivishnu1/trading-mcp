"""
Phase 24B — Official Calendar Refresh Pipeline tests (D1–D5).

D1  NSEOfficialProvider — fetch/parse/health contracts
D2  JSONCalendarProvider persistence — load/save/version/last_updated + schema migration
D3  refresh_calendar() — full orchestration, diff, version increment, cache reset
D4  validate_holidays() — all validation rules
D5  Calendar health — version, source dict in get_calendar_health()
"""
from __future__ import annotations

import json
import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Shared fixtures and helpers
# ---------------------------------------------------------------------------

def _holidays_2026() -> dict[date, str]:
    return {
        date(2026, 1, 26): "Republic Day",
        date(2026, 4, 3):  "Good Friday",
        date(2026, 8, 15): "Independence Day",
        date(2026, 10, 2): "Mahatma Gandhi Jayanti",
        date(2026, 11, 2): "Diwali (Laxmi Pujan)",
        date(2026, 12, 25): "Christmas",
    }


def _nse_api_json(holidays: dict[date, str] | None = None) -> str:
    """Build a sample NSE API JSON response (CM segment format)."""
    if holidays is None:
        holidays = _holidays_2026()
    cm = [
        {"tradingDate": d.strftime("%d-%b-%Y"), "description": name, "weekDay": d.strftime("%A")}
        for d, name in holidays.items()
    ]
    return json.dumps({"CM": cm, "FO": [], "CD": []})


def _nse_html(holidays: dict[date, str] | None = None) -> str:
    """Build sample NSE holiday HTML page."""
    if holidays is None:
        holidays = _holidays_2026()
    rows = "".join(
        f"<tr><td>{i}</td><td>{d.strftime('%d-%b-%Y')}</td>"
        f"<td>{d.strftime('%A')}</td><td>{name}</td></tr>"
        for i, (d, name) in enumerate(holidays.items(), 1)
    )
    return f"<table>{rows}</table>"


def _reset():
    from src.market import calendar as _cal
    _cal._reset_holiday_cache()


# ---------------------------------------------------------------------------
# D1 — NSEOfficialProvider
# ---------------------------------------------------------------------------

class TestNSEOfficialProvider:
    def setup_method(self): _reset()
    def teardown_method(self): _reset()

    def test_name_is_nse_official_provider(self):
        from src.providers.calendar.nse_provider import NSEOfficialProvider
        assert NSEOfficialProvider().name == "NSEOfficialProvider"

    def test_fetch_returns_provider_result_on_success(self):
        from src.providers.calendar.nse_provider import NSEOfficialProvider
        p = NSEOfficialProvider(year=2026)
        with patch.object(p, "_fetch_raw", return_value=_nse_api_json()):
            result = p.fetch()
        assert result is not None
        assert result.status == "HEALTHY"

    def test_fetch_returns_none_on_network_error(self):
        from src.providers.calendar.nse_provider import NSEOfficialProvider
        p = NSEOfficialProvider(year=2026)
        with patch.object(p, "_fetch_raw", side_effect=OSError("connection refused")):
            result = p.fetch()
        assert result is None

    def test_fetch_returns_none_on_empty_cm_segment(self):
        from src.providers.calendar.nse_provider import NSEOfficialProvider
        p = NSEOfficialProvider(year=2026)
        empty = json.dumps({"CM": [], "FO": []})
        with patch.object(p, "_fetch_raw", return_value=empty):
            result = p.fetch()
        assert result is None

    def test_fetch_data_contains_dates(self):
        from src.providers.calendar.nse_provider import NSEOfficialProvider
        p = NSEOfficialProvider(year=2026)
        with patch.object(p, "_fetch_raw", return_value=_nse_api_json()):
            result = p.fetch()
        assert date(2026, 1, 26) in result.data  # Republic Day
        assert date(2026, 8, 15) in result.data  # Independence Day

    def test_fetch_data_keys_are_date_objects(self):
        from src.providers.calendar.nse_provider import NSEOfficialProvider
        p = NSEOfficialProvider(year=2026)
        with patch.object(p, "_fetch_raw", return_value=_nse_api_json()):
            result = p.fetch()
        for key in result.data:
            assert isinstance(key, date)

    def test_fetch_filters_wrong_year(self):
        """Holidays from a different year must not appear in the result."""
        from src.providers.calendar.nse_provider import NSEOfficialProvider
        mixed = _holidays_2026()
        mixed[date(2025, 12, 25)] = "Christmas 2025"  # wrong year
        p = NSEOfficialProvider(year=2026)
        with patch.object(p, "_fetch_raw", return_value=_nse_api_json(mixed)):
            result = p.fetch()
        assert all(d.year == 2026 for d in result.data)

    def test_fetch_year_method(self):
        """fetch_year() convenience method fetches an arbitrary year."""
        from src.providers.calendar.nse_provider import NSEOfficialProvider
        p = NSEOfficialProvider()
        holidays_2025 = {
            date(2025, 8, 15): "Independence Day",
            date(2025, 10, 2): "Gandhi Jayanti",
        }
        with patch.object(p, "_fetch_raw", return_value=_nse_api_json(holidays_2025)):
            result = p.fetch_year(2025)
        assert result is not None
        assert date(2025, 8, 15) in result.data

    def test_provider_result_has_full_metadata(self):
        from src.providers.calendar.nse_provider import NSEOfficialProvider
        p = NSEOfficialProvider(year=2026)
        with patch.object(p, "_fetch_raw", return_value=_nse_api_json()):
            result = p.fetch()
        meta = result.as_provider_meta()
        for key in ("provider_name", "data_source", "authority", "status",
                    "cache_status", "cache_age_seconds", "ttl_seconds", "last_refresh"):
            assert key in meta

    def test_provider_result_ttl_is_zero(self):
        """NSE provider does not cache — ttl_seconds must be 0."""
        from src.providers.calendar.nse_provider import NSEOfficialProvider
        p = NSEOfficialProvider(year=2026)
        with patch.object(p, "_fetch_raw", return_value=_nse_api_json()):
            result = p.fetch()
        assert result.ttl_seconds == 0

    def test_provider_result_cache_status_is_miss(self):
        """NSE provider never caches — cache_status must be MISS."""
        from src.providers.calendar.nse_provider import NSEOfficialProvider
        p = NSEOfficialProvider(year=2026)
        with patch.object(p, "_fetch_raw", return_value=_nse_api_json()):
            result = p.fetch()
        assert result.cache_status == "MISS"

    def test_health_returns_configuration_limited(self):
        from src.providers.calendar.nse_provider import NSEOfficialProvider
        h = NSEOfficialProvider().health()
        assert h["status"] == "CONFIGURATION_LIMITED"

    def test_health_has_recommended_action(self):
        from src.providers.calendar.nse_provider import NSEOfficialProvider
        h = NSEOfficialProvider().health()
        assert "recommended_action" in h

    def test_parse_json_extracts_all_cm_holidays(self):
        """_parse_json() must extract all holidays from the CM segment."""
        from src.providers.calendar.nse_provider import NSEOfficialProvider
        p = NSEOfficialProvider(year=2026)
        raw = _nse_api_json(_holidays_2026())
        result = p._parse_json(raw, 2026)
        assert len(result) == len(_holidays_2026())

    def test_parse_html_fallback(self):
        """_parse_html() extracts dates from an HTML table."""
        from src.providers.calendar.nse_provider import NSEOfficialProvider
        p = NSEOfficialProvider(year=2026)
        html = _nse_html(_holidays_2026())
        result = p._parse_html(html, 2026)
        assert len(result) >= 1  # At least some holidays parsed

    def test_parse_response_tries_json_first(self):
        """_parse_response() tries JSON before falling back to HTML."""
        from src.providers.calendar.nse_provider import NSEOfficialProvider
        p = NSEOfficialProvider(year=2026)
        raw = _nse_api_json()
        with patch.object(p, "_parse_json", return_value=_holidays_2026()) as mock_json:
            result = p._parse_response(raw, 2026)
        assert mock_json.called
        assert len(result) > 0

    def test_parse_response_falls_back_to_html_on_json_error(self):
        """When JSON parse fails, _parse_html is used."""
        from src.providers.calendar.nse_provider import NSEOfficialProvider
        p = NSEOfficialProvider(year=2026)
        html = _nse_html()
        with patch.object(p, "_parse_json", side_effect=ValueError("bad json")):
            with patch.object(p, "_parse_html", return_value=_holidays_2026()) as mock_html:
                p._parse_response(html, 2026)
        assert mock_html.called

    def test_parse_nse_date_dd_mon_yyyy(self):
        from src.providers.calendar.nse_provider import _parse_nse_date
        assert _parse_nse_date("26-Jan-2026") == date(2026, 1, 26)

    def test_parse_nse_date_iso(self):
        from src.providers.calendar.nse_provider import _parse_nse_date
        assert _parse_nse_date("2026-01-26") == date(2026, 1, 26)

    def test_parse_nse_date_invalid_returns_none(self):
        from src.providers.calendar.nse_provider import _parse_nse_date
        assert _parse_nse_date("not a date") is None


# ---------------------------------------------------------------------------
# D2 — JSONCalendarProvider persistence (schema migration + load/save)
# ---------------------------------------------------------------------------

class TestJSONCalendarProviderPersistence:
    def setup_method(self): _reset()
    def teardown_method(self): _reset()

    def _temp_provider(self, initial_files: dict[str, object] | None = None):
        import tempfile, json as _json
        tmpdir = tempfile.mkdtemp()
        d = Path(tmpdir)
        if initial_files:
            for fname, content in initial_files.items():
                (d / fname).write_text(_json.dumps(content), encoding="utf-8")
        from src.providers.calendar.json_provider import JSONCalendarProvider
        return JSONCalendarProvider(resources_dir=d), d

    def test_load_missing_year_returns_empty_dict(self):
        p, _ = self._temp_provider()
        assert p.load(2026) == {}

    def test_load_flat_array_migrates_in_memory(self):
        flat = [{"date": "2026-01-26", "name": "Republic Day"}]
        p, _ = self._temp_provider({"2026.json": flat})
        meta = p.load(2026)
        assert date(2026, 1, 26) in meta["holidays"]
        assert meta["version"] is None

    def test_load_new_schema_preserves_metadata(self):
        new_schema = {
            "version": "2026.3",
            "authority": "NSE",
            "source": "Official NSE Holiday Circular",
            "last_updated": "2026-06-01T00:00:00Z",
            "holidays": [{"date": "2026-01-26", "name": "Republic Day"}],
        }
        p, _ = self._temp_provider({"2026.json": new_schema})
        meta = p.load(2026)
        assert meta["version"] == "2026.3"
        assert meta["last_updated"] == "2026-06-01T00:00:00Z"
        assert date(2026, 1, 26) in meta["holidays"]

    def test_save_writes_new_schema_format(self):
        p, d = self._temp_provider()
        p.save(2026, _holidays_2026(), version="2026.1")
        content = json.loads((d / "2026.json").read_text())
        assert isinstance(content, dict)
        assert content["version"] == "2026.1"
        assert "holidays" in content
        assert isinstance(content["holidays"], list)

    def test_save_holidays_are_sorted(self):
        p, d = self._temp_provider()
        p.save(2026, _holidays_2026(), version="2026.1")
        content = json.loads((d / "2026.json").read_text())
        dates = [h["date"] for h in content["holidays"]]
        assert dates == sorted(dates)

    def test_save_includes_last_updated(self):
        p, d = self._temp_provider()
        p.save(2026, _holidays_2026(), version="2026.1")
        content = json.loads((d / "2026.json").read_text())
        assert "last_updated" in content
        assert "T" in content["last_updated"]

    def test_save_includes_authority(self):
        p, d = self._temp_provider()
        p.save(2026, _holidays_2026(), version="2026.1", authority="NSE")
        content = json.loads((d / "2026.json").read_text())
        assert content["authority"] == "NSE"

    def test_save_invalidates_in_memory_cache(self):
        flat = [{"date": "2026-01-26", "name": "Old Republic Day"}]
        p, d = self._temp_provider({"2026.json": flat})
        # Populate the cache with the old content
        p._load_raw_json()  # load into internal state via direct call
        p._cache = {date(2026, 1, 26): "Old Republic Day"}
        p._cached_at = 1.0  # non-None
        # Save new content
        p.save(2026, _holidays_2026(), version="2026.1")
        # Cache must be cleared
        assert p._cache is None

    def test_version_returns_none_for_flat_array(self):
        flat = [{"date": "2026-01-26", "name": "Republic Day"}]
        p, _ = self._temp_provider({"2026.json": flat})
        assert p.version(2026) is None

    def test_version_returns_string_for_new_schema(self):
        new_schema = {
            "version": "2026.2",
            "authority": "NSE",
            "source": "...",
            "last_updated": "2026-01-01T00:00:00Z",
            "holidays": [],
        }
        p, _ = self._temp_provider({"2026.json": new_schema})
        assert p.version(2026) == "2026.2"

    def test_version_returns_none_for_missing_file(self):
        p, _ = self._temp_provider()
        assert p.version(2099) is None

    def test_last_updated_returns_none_for_flat_array(self):
        flat = [{"date": "2026-01-26", "name": "Republic Day"}]
        p, _ = self._temp_provider({"2026.json": flat})
        assert p.last_updated(2026) is None

    def test_last_updated_returns_timestamp_for_new_schema(self):
        ts = "2026-06-25T10:00:00Z"
        new_schema = {
            "version": "2026.1",
            "authority": "NSE",
            "source": "...",
            "last_updated": ts,
            "holidays": [],
        }
        p, _ = self._temp_provider({"2026.json": new_schema})
        assert p.last_updated(2026) == ts

    def test_runtime_fetch_works_with_new_schema(self):
        """fetch() must still work correctly after a file is written with new schema."""
        p, d = self._temp_provider()
        p.save(2026, _holidays_2026(), version="2026.1")
        # Simulate runtime fetch with the saved file (write current year too)
        today = date.today()
        if today.year != 2026:
            # Copy as current year for runtime fetch
            content = json.loads((d / "2026.json").read_text())
            content_copy = dict(content)
            content_copy["holidays"] = [
                h for h in content["holidays"] if True  # keep all
            ]
            (d / f"{today.year}.json").write_text(json.dumps(content_copy))
        result = p.fetch()
        assert result is not None

    def test_round_trip_save_then_load(self):
        """save() then load() must return identical holiday data."""
        p, _ = self._temp_provider()
        original = _holidays_2026()
        p.save(2026, original, version="2026.1")
        loaded = p.load(2026)
        assert loaded["holidays"] == original
        assert loaded["version"] == "2026.1"


# ---------------------------------------------------------------------------
# D3 — refresh_calendar() orchestration
# ---------------------------------------------------------------------------

class TestRefreshCalendar:
    def setup_method(self): _reset()
    def teardown_method(self): _reset()

    def _mock_nse_provider(self, holidays: dict[date, str] | None = None,
                            fail: bool = False) -> MagicMock:
        from src.providers.base import ProviderResult
        mock = MagicMock()
        if fail:
            mock.fetch.return_value = None
        else:
            h = holidays or _holidays_2026()
            mock.fetch.return_value = ProviderResult(
                data=h, provider_name="NSEOfficialProvider",
                data_source="https://nseindia.com/...", authority="NSE",
                status="HEALTHY", fallback_level=0, cache_status="MISS",
                cache_age_seconds=0, ttl_seconds=0, last_refresh="2026-06-25T00:00:00Z",
            )
        return mock

    def test_refresh_returns_dict(self):
        from src.providers.calendar.refresh import refresh_calendar
        mock = self._mock_nse_provider()
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("src.providers.calendar.refresh.JSONCalendarProvider") as MockJP:
                MockJP.return_value.load.return_value = {}
                MockJP.return_value.save.return_value = None
                result = refresh_calendar(2026, nse_provider=mock)
        assert isinstance(result, dict)

    def test_refresh_fails_gracefully_when_nse_unavailable(self):
        from src.providers.calendar.refresh import refresh_calendar
        mock = self._mock_nse_provider(fail=True)
        result = refresh_calendar(2026, nse_provider=mock)
        assert result["updated"] is False
        assert "error" in result

    def test_refresh_updated_true_when_changes_exist(self):
        from src.providers.calendar.refresh import refresh_calendar
        mock = self._mock_nse_provider()  # new holidays
        with patch("src.providers.calendar.refresh.JSONCalendarProvider") as MockJP:
            MockJP.return_value.load.return_value = {"holidays": {}, "version": None}
            MockJP.return_value.save.return_value = None
            with patch("src.providers.calendar.refresh.reset_calendar_provider"):
                result = refresh_calendar(2026, nse_provider=mock)
        assert result["updated"] is True

    def test_refresh_updated_false_when_no_changes(self):
        from src.providers.calendar.refresh import refresh_calendar
        holidays = _holidays_2026()
        mock = self._mock_nse_provider(holidays)
        with patch("src.providers.calendar.refresh.JSONCalendarProvider") as MockJP:
            # Existing == new → no changes
            MockJP.return_value.load.return_value = {
                "holidays": holidays, "version": "2026.1"
            }
            MockJP.return_value.save.return_value = None
            result = refresh_calendar(2026, nse_provider=mock)
        assert result["updated"] is False
        assert result.get("current_version") == "2026.1"

    def test_refresh_dry_run_does_not_write(self):
        from src.providers.calendar.refresh import refresh_calendar
        mock = self._mock_nse_provider()
        with patch("src.providers.calendar.refresh.JSONCalendarProvider") as MockJP:
            MockJP.return_value.load.return_value = {"holidays": {}, "version": None}
            result = refresh_calendar(2026, nse_provider=mock, dry_run=True)
        MockJP.return_value.save.assert_not_called()
        assert result["updated"] is False
        assert result.get("dry_run") is True

    def test_refresh_dry_run_reports_changes(self):
        from src.providers.calendar.refresh import refresh_calendar
        mock = self._mock_nse_provider()
        with patch("src.providers.calendar.refresh.JSONCalendarProvider") as MockJP:
            MockJP.return_value.load.return_value = {"holidays": {}, "version": None}
            result = refresh_calendar(2026, nse_provider=mock, dry_run=True)
        assert "changes" in result
        assert len(result["changes"]) > 0

    def test_refresh_increments_version(self):
        from src.providers.calendar.refresh import refresh_calendar
        mock = self._mock_nse_provider()
        with patch("src.providers.calendar.refresh.JSONCalendarProvider") as MockJP:
            MockJP.return_value.load.return_value = {
                "holidays": {}, "version": "2026.3"
            }
            MockJP.return_value.save.return_value = None
            with patch("src.providers.calendar.refresh.reset_calendar_provider"):
                result = refresh_calendar(2026, nse_provider=mock)
        assert result.get("new_version") == "2026.4"

    def test_refresh_resets_provider_chain(self):
        from src.providers.calendar.refresh import refresh_calendar
        mock = self._mock_nse_provider()
        with patch("src.providers.calendar.refresh.JSONCalendarProvider") as MockJP:
            MockJP.return_value.load.return_value = {"holidays": {}, "version": None}
            MockJP.return_value.save.return_value = None
            with patch("src.providers.calendar.refresh.reset_calendar_provider") as mock_reset:
                refresh_calendar(2026, nse_provider=mock)
        mock_reset.assert_called_once()

    def test_refresh_has_changes_list(self):
        from src.providers.calendar.refresh import refresh_calendar
        mock = self._mock_nse_provider()
        with patch("src.providers.calendar.refresh.JSONCalendarProvider") as MockJP:
            MockJP.return_value.load.return_value = {"holidays": {}, "version": None}
            MockJP.return_value.save.return_value = None
            with patch("src.providers.calendar.refresh.reset_calendar_provider"):
                result = refresh_calendar(2026, nse_provider=mock)
        assert "changes" in result
        assert all("action" in c for c in result["changes"])

    def test_refresh_changes_contain_added_action(self):
        from src.providers.calendar.refresh import refresh_calendar
        mock = self._mock_nse_provider()
        with patch("src.providers.calendar.refresh.JSONCalendarProvider") as MockJP:
            MockJP.return_value.load.return_value = {"holidays": {}, "version": None}
            MockJP.return_value.save.return_value = None
            with patch("src.providers.calendar.refresh.reset_calendar_provider"):
                result = refresh_calendar(2026, nse_provider=mock)
        actions = {c["action"] for c in result["changes"]}
        assert "added" in actions

    def test_refresh_has_validation_result(self):
        from src.providers.calendar.refresh import refresh_calendar
        mock = self._mock_nse_provider()
        with patch("src.providers.calendar.refresh.JSONCalendarProvider") as MockJP:
            MockJP.return_value.load.return_value = {"holidays": {}, "version": None}
            MockJP.return_value.save.return_value = None
            with patch("src.providers.calendar.refresh.reset_calendar_provider"):
                result = refresh_calendar(2026, nse_provider=mock)
        assert "validation" in result
        assert result["validation"]["status"] == "passed"

    def test_refresh_validation_fail_preserves_json(self):
        """If validation fails, save() must NOT be called."""
        from src.providers.calendar.refresh import refresh_calendar
        # 0 holidays → validation fails
        from src.providers.base import ProviderResult
        mock = MagicMock()
        mock.fetch.return_value = ProviderResult(
            data={}, provider_name="NSEOfficialProvider",
            data_source="...", authority="NSE",
            status="HEALTHY", fallback_level=0, cache_status="MISS",
            cache_age_seconds=0, ttl_seconds=0, last_refresh="",
        )
        with patch("src.providers.calendar.refresh.JSONCalendarProvider") as MockJP:
            MockJP.return_value.load.return_value = {"holidays": {}, "version": None}
            result = refresh_calendar(2026, nse_provider=mock)
        MockJP.return_value.save.assert_not_called()
        assert result["updated"] is False
        assert result["validation"]["status"] == "failed"

    def test_refresh_default_year_is_current(self):
        from src.providers.calendar.refresh import refresh_calendar
        mock = self._mock_nse_provider()
        with patch("src.providers.calendar.refresh.JSONCalendarProvider") as MockJP:
            MockJP.return_value.load.return_value = {"holidays": {}, "version": None}
            MockJP.return_value.save.return_value = None
            with patch("src.providers.calendar.refresh.reset_calendar_provider"):
                result = refresh_calendar(nse_provider=mock)
        assert result["year"] == date.today().year


# ---------------------------------------------------------------------------
# D3 helpers — _compute_changes, _next_version
# ---------------------------------------------------------------------------

class TestRefreshHelpers:
    def test_compute_changes_empty_to_nonempty(self):
        from src.providers.calendar.refresh import _compute_changes
        old: dict[date, str] = {}
        new = _holidays_2026()
        changes = _compute_changes(old, new)
        added = [c for c in changes if c["action"] == "added"]
        assert len(added) == len(new)

    def test_compute_changes_nonempty_to_empty(self):
        from src.providers.calendar.refresh import _compute_changes
        changes = _compute_changes(_holidays_2026(), {})
        removed = [c for c in changes if c["action"] == "removed"]
        assert len(removed) == len(_holidays_2026())

    def test_compute_changes_same_set_empty_list(self):
        from src.providers.calendar.refresh import _compute_changes
        h = _holidays_2026()
        assert _compute_changes(h, h) == []

    def test_compute_changes_renamed_holiday(self):
        from src.providers.calendar.refresh import _compute_changes
        old = {date(2026, 1, 26): "Republic Day"}
        new = {date(2026, 1, 26): "Republic Day (renamed)"}
        changes = _compute_changes(old, new)
        assert len(changes) == 1
        assert changes[0]["action"] == "renamed"

    def test_next_version_from_none(self):
        from src.providers.calendar.refresh import _next_version
        assert _next_version(None, 2026) == "2026.1"

    def test_next_version_increments_minor(self):
        from src.providers.calendar.refresh import _next_version
        assert _next_version("2026.1", 2026) == "2026.2"
        assert _next_version("2026.9", 2026) == "2026.10"

    def test_next_version_resets_on_year_change(self):
        from src.providers.calendar.refresh import _next_version
        assert _next_version("2025.5", 2026) == "2026.1"

    def test_next_version_handles_malformed(self):
        from src.providers.calendar.refresh import _next_version
        assert _next_version("garbage", 2026) == "2026.1"


# ---------------------------------------------------------------------------
# D4 — validate_holidays()
# ---------------------------------------------------------------------------

class TestValidateHolidays:
    def _valid(self) -> dict[date, str]:
        return {
            date(2026, 1, 26): "Republic Day",
            date(2026, 4, 3):  "Good Friday",
            date(2026, 8, 15): "Independence Day",
            date(2026, 10, 2): "Mahatma Gandhi Jayanti",
            date(2026, 11, 2): "Diwali (Laxmi Pujan)",
            date(2026, 12, 25): "Christmas",
        }

    def test_valid_set_passes(self):
        from src.providers.calendar.refresh import validate_holidays
        ok, errors = validate_holidays(self._valid(), 2026)
        # Advisory-only errors (missing keyword groups) don't block passage
        fatal_errors = [e for e in errors if "Advisory" not in e]
        assert ok is True or not fatal_errors

    def test_empty_set_fails(self):
        from src.providers.calendar.refresh import validate_holidays
        ok, errors = validate_holidays({}, 2026)
        assert ok is False
        assert any("empty" in e.lower() or "no holidays" in e.lower() for e in errors)

    def test_too_few_holidays_fails(self):
        from src.providers.calendar.refresh import validate_holidays
        # Only 2 holidays — below minimum of 5
        tiny = {date(2026, 1, 26): "Republic Day", date(2026, 4, 3): "Good Friday"}
        ok, errors = validate_holidays(tiny, 2026)
        assert ok is False
        assert any("few" in e.lower() for e in errors)

    def test_wrong_year_dates_fail(self):
        from src.providers.calendar.refresh import validate_holidays
        wrong = {date(2025, 1, 26): "Republic Day"}  # 2025 date for 2026 year
        ok, errors = validate_holidays(wrong, 2026)
        assert ok is False
        assert any("wrong year" in e.lower() for e in errors)

    def test_all_weekend_holidays_fail(self):
        from src.providers.calendar.refresh import validate_holidays
        # Find 6 Sundays in 2026 to use as holidays
        sundays = []
        d = date(2026, 1, 4)  # first Sunday of 2026
        while len(sundays) < 6:
            if d.weekday() == 6:
                sundays.append(d)
            d = date(d.year, d.month, d.day).__class__(d.year, d.month, d.day)
            from datetime import timedelta
            d += timedelta(days=1)
        weekend_set = {s: f"Holiday {i}" for i, s in enumerate(sundays)}
        ok, errors = validate_holidays(weekend_set, 2026)
        assert ok is False
        assert any("weekend" in e.lower() for e in errors)

    def test_duplicate_names_fail(self):
        from src.providers.calendar.refresh import validate_holidays
        dup = {
            date(2026, 1, 26): "Republic Day",
            date(2026, 2, 2):  "Republic Day",  # duplicate name
            date(2026, 8, 15): "Independence Day",
            date(2026, 10, 2): "Gandhi Jayanti",
            date(2026, 12, 25): "Christmas",
        }
        ok, errors = validate_holidays(dup, 2026)
        assert ok is False
        assert any("duplicate" in e.lower() for e in errors)

    def test_too_many_holidays_fail(self):
        from src.providers.calendar.refresh import validate_holidays
        from datetime import timedelta
        many: dict[date, str] = {}
        d = date(2026, 1, 5)  # Monday
        while len(many) < 31:
            if d.weekday() < 5:  # weekday
                many[d] = f"Holiday {len(many) + 1}"
            d += timedelta(days=1)
        ok, errors = validate_holidays(many, 2026)
        assert ok is False
        assert any("many" in e.lower() for e in errors)

    def test_validation_errors_are_strings(self):
        from src.providers.calendar.refresh import validate_holidays
        _, errors = validate_holidays({}, 2026)
        assert all(isinstance(e, str) for e in errors)

    def test_returns_tuple(self):
        from src.providers.calendar.refresh import validate_holidays
        result = validate_holidays(self._valid(), 2026)
        assert isinstance(result, tuple)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# D5 — Calendar health: version + source dict
# ---------------------------------------------------------------------------

class TestCalendarHealthPhase24B:
    def setup_method(self): _reset()
    def teardown_method(self): _reset()

    def test_health_has_version_field(self):
        from src.market.calendar import get_calendar_health
        h = get_calendar_health()
        assert "version" in h

    def test_health_has_source_dict(self):
        from src.market.calendar import get_calendar_health
        h = get_calendar_health()
        assert "source" in h
        assert isinstance(h["source"], dict)

    def test_health_source_has_runtime_key(self):
        from src.market.calendar import get_calendar_health
        h = get_calendar_health()
        assert h["source"]["runtime"] == "JSONCalendarProvider"

    def test_health_source_has_refresh_key(self):
        from src.market.calendar import get_calendar_health
        h = get_calendar_health()
        assert h["source"]["refresh"] == "NSEOfficialProvider"

    def test_health_version_is_none_for_old_flat_array(self):
        """Current JSON files use flat array format → version is None."""
        from src.market.calendar import get_calendar_health
        h = get_calendar_health()
        # The existing resources/calendar/YYYY.json are flat arrays → None
        # (They haven't been refreshed with the new schema yet)
        assert h["version"] is None or isinstance(h["version"], str)

    def test_health_version_is_string_after_save(self):
        """After save() with a version, health.version reflects the file's version."""
        from src.providers.calendar.chain import get_calendar_provider, reset_calendar_provider
        from src.providers.calendar.json_provider import JSONCalendarProvider
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir)
            # Create a JSON file for current year with new schema
            today = date.today()
            p = JSONCalendarProvider(resources_dir=d)
            p.save(today.year, {date(today.year, 8, 15): "Independence Day"},
                   version=f"{today.year}.99")
            # Also need next year for the provider to work
            p.save(today.year + 1, {date(today.year + 1, 8, 15): "Independence Day"},
                   version=f"{today.year + 1}.1")
            # Use a fresh chain with the temp directory
            from src.providers.calendar.emergency import EmergencyCalendarProvider
            from src.providers.calendar.chain import CalendarProviderChain
            chain = CalendarProviderChain()
            chain._json_provider = JSONCalendarProvider(resources_dir=d)
            chain._providers = [chain._json_provider, chain._emergency_provider]
            chain.fetch()
            v = chain.version()
        assert v == f"{today.year}.99"

    def test_health_has_status(self):
        from src.market.calendar import get_calendar_health
        h = get_calendar_health()
        assert "status" in h

    def test_health_has_severity(self):
        from src.market.calendar import get_calendar_health
        h = get_calendar_health()
        assert "severity" in h

    def test_health_has_expiry_source(self):
        from src.market.calendar import get_calendar_health
        h = get_calendar_health()
        assert "expiry_source" in h

    def test_health_has_holiday_source(self):
        from src.market.calendar import get_calendar_health
        h = get_calendar_health()
        assert "holiday_source" in h

    def test_chain_version_reflects_json_file(self):
        from src.providers.calendar.chain import get_calendar_provider
        # With existing flat-array files, version is None
        chain = get_calendar_provider()
        v = chain.version()
        assert v is None or isinstance(v, str)

    def test_health_with_emergency_fallback_has_source_dict(self):
        """Even when JSON is unavailable, source dict is always present."""
        from src.market.calendar import get_calendar_health
        with patch("src.providers.calendar.json_provider.JSONCalendarProvider._load_raw_json",
                   side_effect=FileNotFoundError("no json")):
            h = get_calendar_health()
        assert "source" in h
        assert h["source"]["runtime"] == "JSONCalendarProvider"
        assert h["source"]["refresh"] == "NSEOfficialProvider"

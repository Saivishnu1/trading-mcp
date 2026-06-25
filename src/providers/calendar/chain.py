"""
Calendar provider chain — Phase 24A (D2, D7).

Singleton chain: JSONCalendarProvider → EmergencyCalendarProvider.

Public API:
  get_calendar_provider()     → CalendarProviderChain (singleton)
  reset_calendar_provider()   → clears singleton + JSON cache (for tests)
"""
from __future__ import annotations

from src.providers.base import ProviderResult
from src.providers.calendar.emergency import EmergencyCalendarProvider
from src.providers.calendar.json_provider import JSONCalendarProvider

_HEALTH_SEVERITY: dict[str, str] = {
    "HEALTHY":   "INFO",
    "CACHED":    "INFO",
    "EMERGENCY": "WARNING",
    "OFFLINE":   "WARNING",
    "FAILED":    "ERROR",
}

_STATUS_TO_HOLIDAY_SOURCE: dict[str, str] = {
    "HEALTHY":   "json",
    "CACHED":    "cache",
    "EMERGENCY": "emergency",
    "FAILED":    "unknown",
}


class CalendarProviderChain:
    """Tries each provider in order and returns the first successful result."""

    def __init__(self) -> None:
        self._json_provider = JSONCalendarProvider()
        self._emergency_provider = EmergencyCalendarProvider()
        self._providers = [self._json_provider, self._emergency_provider]
        self._last_result: ProviderResult | None = None

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def fetch(self) -> ProviderResult:
        for provider in self._providers:
            try:
                result = provider.fetch()
                if result is not None:
                    self._last_result = result
                    return result
            except Exception:
                pass
        # EmergencyCalendarProvider never returns None, so reaching here means
        # something very unexpected happened — return a failure marker.
        from src.providers.base import _now_iso
        from datetime import date
        failed: ProviderResult = ProviderResult(
            data={},
            provider_name="CalendarProviderChain",
            data_source="none",
            authority="none",
            status="FAILED",
            fallback_level=99,
            cache_status="BYPASS",
            cache_age_seconds=0,
            ttl_seconds=0,
            last_refresh=_now_iso(),
        )
        self._last_result = failed
        return failed

    def health(self) -> dict:
        if self._last_result is None:
            return {
                "status": "OFFLINE",
                "severity": "WARNING",
                "holiday_source": "unknown",
                "reason": "Calendar provider has not been fetched yet.",
                "recommended_action": "Call get_market_calendar() to initialize.",
            }
        result = self._last_result
        status = result.status
        severity = _HEALTH_SEVERITY.get(status, "WARNING")
        holiday_source = _STATUS_TO_HOLIDAY_SOURCE.get(status, "unknown")
        base: dict = {
            "status": status,
            "severity": severity,
            "holiday_source": holiday_source,
            "provider": result.provider_name,
            "data_source": result.data_source,
        }
        if status == "EMERGENCY":
            base["reason"] = "JSON calendar unavailable; serving embedded emergency set."
            base["recommended_action"] = "Verify resources/calendar/YYYY.json files exist."
        elif status == "CACHED":
            base["cache_age_seconds"] = result.cache_age_seconds
            base["ttl_seconds"] = result.ttl_seconds
            base["last_refresh"] = result.last_refresh
        elif status == "HEALTHY":
            base["last_refresh"] = result.last_refresh
        elif status == "FAILED":
            base["reason"] = "All calendar providers failed."
            base["recommended_action"] = "Check provider chain configuration."
            base["severity"] = "ERROR"
        return base

    def reset(self) -> None:
        """Flush all caches — used by _reset_holiday_cache() and tests."""
        self._json_provider.reset()
        self._last_result = None

    def version(self) -> str | None:
        """Return the current year's JSON file version (None for old flat-array files)."""
        from datetime import date
        return self._json_provider.version(date.today().year)

    @property
    def last_result(self) -> ProviderResult | None:
        return self._last_result


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_CHAIN: CalendarProviderChain | None = None


def get_calendar_provider() -> CalendarProviderChain:
    global _CHAIN
    if _CHAIN is None:
        _CHAIN = CalendarProviderChain()
    return _CHAIN


def reset_calendar_provider() -> None:
    """Fully reset the singleton (creates a fresh chain on next get_calendar_provider())."""
    global _CHAIN
    if _CHAIN is not None:
        _CHAIN.reset()
    _CHAIN = None

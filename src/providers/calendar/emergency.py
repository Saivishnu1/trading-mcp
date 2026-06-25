"""
Emergency calendar provider — Phase 24A (D4).

Contains a minimal hardcoded set of critical NSE holidays for the current year.
This is the last resort when JSON files are unavailable. The list intentionally
covers only the most widely known NSE holidays to keep the embedded payload small.
"""
from __future__ import annotations

from datetime import date

from src.providers.base import BaseProvider, ProviderResult, _now_iso

# Minimal hardcoded holidays: one entry per likely trading-day holiday.
# Missing entries are better than wrong entries — the JSON files carry the full list.
_EMERGENCY_HOLIDAYS: dict[int, dict[date, str]] = {
    2025: {
        date(2025, 2, 26): "Mahashivratri",
        date(2025, 3, 14): "Holi",
        date(2025, 3, 31): "Id-Ul-Fitr",
        date(2025, 4, 14): "Ambedkar Jayanti",
        date(2025, 4, 18): "Good Friday",
        date(2025, 5, 1):  "Maharashtra Day",
        date(2025, 8, 15): "Independence Day",
        date(2025, 10, 2): "Gandhi Jayanti",
        date(2025, 10, 20): "Diwali",
        date(2025, 12, 25): "Christmas",
    },
    2026: {
        date(2026, 1, 26): "Republic Day",
        date(2026, 4, 3):  "Good Friday",
        date(2026, 4, 14): "Ambedkar Jayanti",
        date(2026, 8, 15): "Independence Day",
        date(2026, 10, 2): "Gandhi Jayanti",
        date(2026, 11, 2): "Diwali (Laxmi Pujan)",
        date(2026, 12, 25): "Christmas",
    },
    2027: {
        date(2027, 1, 26): "Republic Day",
        date(2027, 3, 26): "Good Friday",
        date(2027, 8, 15): "Independence Day",
        date(2027, 10, 21): "Diwali",
        date(2027, 12, 25): "Christmas",
    },
    2028: {
        date(2028, 1, 26): "Republic Day",
        date(2028, 4, 14): "Good Friday",
        date(2028, 8, 15): "Independence Day",
        date(2028, 10, 2): "Gandhi Jayanti",
        date(2028, 11, 9): "Diwali",
        date(2028, 12, 25): "Christmas",
    },
}


class EmergencyCalendarProvider(BaseProvider):
    """Returns a minimal hardcoded holiday set when all other providers fail."""

    @property
    def name(self) -> str:
        return "EmergencyCalendarProvider"

    def fetch(self) -> ProviderResult:
        today = date.today()
        # Merge current and next year for upcoming-holiday queries
        holidays: dict[date, str] = {}
        for year in (today.year, today.year + 1):
            holidays.update(_EMERGENCY_HOLIDAYS.get(year, {}))

        return ProviderResult(
            data=holidays,
            provider_name=self.name,
            data_source="embedded_emergency_calendar",
            authority="NSE Holiday Circular (partial — emergency subset only)",
            status="EMERGENCY",
            fallback_level=2,
            cache_status="BYPASS",
            cache_age_seconds=0,
            ttl_seconds=0,
            last_refresh=_now_iso(),
        )

    def health(self) -> dict:
        return {
            "status": "EMERGENCY",
            "severity": "WARNING",
            "holiday_source": "emergency",
            "reason": "Emergency hardcoded calendar in use — JSON files unavailable.",
            "recommended_action": "Verify resources/calendar/YYYY.json files exist.",
        }

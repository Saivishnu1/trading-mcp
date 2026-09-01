"""
NSE Official Calendar Provider — Phase 24B (D1).

Fetches the official NSE market holiday list for use ONLY during refresh operations.
This provider is NEVER used at runtime — it contacts NSE on demand when
refresh_calendar() is called.

Architecture contract:
  - Runtime holiday serving: JSONCalendarProvider
  - Refresh source:          NSEOfficialProvider (this module)
  - Emergency fallback:      EmergencyCalendarProvider

The provider attempts the NSE JSON API endpoint first, then falls back to
HTML table parsing if the API is unavailable. All HTTP calls are behind
_fetch_raw(), which is easily mocked in tests.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Any

from src.providers.base import BaseProvider, ProviderResult, _now_iso

# ---------------------------------------------------------------------------
# NSE endpoint — cash market (CM) segment holiday list
# ---------------------------------------------------------------------------
_NSE_API_URL = "https://www.nseindia.com/api/holiday-master?type=trading"
_NSE_HTML_URL = "https://www.nseindia.com/resources/exchange-communication-holidays"

_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
    "X-Requested-With": "XMLHttpRequest",
}

# Date formats that NSE uses in API responses and on their web pages
_NSE_DATE_FORMATS = ("%d-%b-%Y", "%Y-%m-%d", "%d/%m/%Y", "%B %d, %Y")

# Known mandatory holidays — if fewer than this many are found, the parse
# is considered suspicious but not invalid.  Validation decides the outcome.
_MIN_EXPECTED_HOLIDAYS = 5


class NSEOfficialProvider(BaseProvider):
    """
    Fetches official NSE holidays from the public NSE API.

    Intended for use by refresh_calendar() only.  Never placed in the
    runtime CalendarProviderChain.
    """

    def __init__(self, year: int | None = None) -> None:
        self._year = year or date.today().year

    @property
    def name(self) -> str:
        return "NSEOfficialProvider"

    # ------------------------------------------------------------------
    # BaseProvider contract
    # ------------------------------------------------------------------

    def fetch(self) -> ProviderResult | None:
        """Fetch holidays for the configured year from NSE."""
        return self._fetch_for_year(self._year)

    def health(self) -> dict:
        """NSEOfficialProvider is refresh-only — not part of the runtime chain."""
        return {
            "status": "CONFIGURATION_LIMITED",
            "severity": "INFO",
            "reason": (
                "NSEOfficialProvider is a refresh-only provider.  "
                "It does not serve runtime requests."
            ),
            "recommended_action": "Call refresh_calendar() to update holiday data from NSE.",
        }

    # ------------------------------------------------------------------
    # Refresh-specific API
    # ------------------------------------------------------------------

    def fetch_year(self, year: int) -> ProviderResult | None:
        """Fetch holidays for an arbitrary year.  Convenience for refresh pipelines."""
        return self._fetch_for_year(year)

    # ------------------------------------------------------------------
    # Internal implementation
    # ------------------------------------------------------------------

    def _fetch_for_year(self, year: int) -> ProviderResult | None:
        """Core fetch logic: HTTP → parse → ProviderResult."""
        try:
            raw = self._fetch_raw()
            holidays = self._parse_response(raw, year)
            if not holidays:
                return None
            return ProviderResult(
                data=holidays,
                provider_name=self.name,
                data_source=_NSE_API_URL,
                authority="NSE Official Holiday Circular",
                status="HEALTHY",
                fallback_level=0,
                cache_status="MISS",
                cache_age_seconds=0,
                ttl_seconds=0,  # No caching — each call is a live fetch
                last_refresh=_now_iso(),
            )
        except Exception:
            return None

    def _fetch_raw(self) -> str:
        """
        Make the HTTP request to NSE API.

        This is the primary mock target in tests.  Production code uses
        urllib.request so there is no extra dependency beyond stdlib.
        """
        import urllib.error
        import urllib.request

        req = urllib.request.Request(_NSE_API_URL, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read().decode("utf-8")

    def _parse_response(self, raw: str, year: int) -> dict[date, str]:
        """Try JSON API format, fall back to HTML table parsing."""
        try:
            return self._parse_json(raw, year)
        except (json.JSONDecodeError, KeyError, ValueError):
            pass
        return self._parse_html(raw, year)

    def _parse_json(self, raw: str, year: int) -> dict[date, str]:
        """
        Parse NSE API JSON response.

        Expected structure:
          {"CM": [{"tradingDate": "26-Jan-2026", "description": "Republic Day", ...}, ...]}

        CM = Cash Market segment (equity trading holidays).
        """
        data: Any = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("NSE response is not a JSON object")

        # NSE may use "CM" or "cm" or similar keys
        segment: list = (
            data.get("CM")
            or data.get("cm")
            or data.get("Capital Market")
            or []
        )
        if not segment:
            raise KeyError(f"No CM segment in NSE response; keys={list(data.keys())}")

        result: dict[date, str] = {}
        for entry in segment:
            date_str = (
                entry.get("tradingDate")
                or entry.get("trading_date")
                or entry.get("date")
                or ""
            )
            name = (
                entry.get("description")
                or entry.get("tradingDescription")
                or entry.get("name")
                or ""
            ).strip()
            if not date_str or not name:
                continue
            d = _parse_nse_date(date_str)
            if d is not None and d.year == year:
                result[d] = name

        return result

    def _parse_html(self, html: str, year: int) -> dict[date, str]:
        """
        Best-effort HTML table parser for the NSE holiday page.

        Looks for <tr> rows whose cells contain recognisable date patterns.
        This is a fallback; the JSON API is strongly preferred.
        """
        result: dict[date, str] = {}

        # Extract all table rows
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.DOTALL | re.IGNORECASE)
        for row in rows:
            # Extract cell text (strip HTML tags)
            cells_raw = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.DOTALL | re.IGNORECASE)
            cells = [re.sub(r"<[^>]+>", "", c).strip() for c in cells_raw]
            cells = [c for c in cells if c]
            if len(cells) < 2:
                continue

            parsed_date: date | None = None
            name_candidate = ""

            for i, cell in enumerate(cells[:4]):   # Check first 4 cells for a date
                d = _parse_nse_date(cell)
                if d is not None and d.year == year:
                    parsed_date = d
                    # Name is the last remaining cell
                    name_candidate = cells[-1] if cells[-1] != cell else (
                        cells[i + 1] if i + 1 < len(cells) else ""
                    )
                    break

            if parsed_date and name_candidate:
                result[parsed_date] = name_candidate

        return result


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _parse_nse_date(raw: str) -> date | None:
    """Try all known NSE date formats; return None if none match."""
    raw = raw.strip()
    for fmt in _NSE_DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            pass
    return None

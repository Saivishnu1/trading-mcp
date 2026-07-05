"""
CalendarFetcher — live NSE + BSE holiday fetching with file-based cache.

NSE source: JSON API (nseindia.com/api/holiday-master) with browser headers.
BSE source: HTML scrape of BSE holiday page.
Cache:      /tmp/nse_holidays_YYYY.json and /tmp/bse_holidays_YYYY.json, 24h TTL.

Fallback chain:
  NSE: live JSON API → cached file → existing NSEOfficialProvider → []
  BSE: live HTML scrape → cached file → NSE holidays (95%+ overlap)
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import date
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 86400  # 24 hours

_NSE_HOLIDAY_URL = "https://www.nseindia.com/api/holiday-master?type=trading"
_NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.nseindia.com",
    "Accept-Language": "en-US,en;q=0.9",
}

# BSE holiday page is a JS-rendered Angular SPA — HTML scrape returns no dates.
# We skip live BSE fetch and rely on the static JSON fallback (bse_YYYY.json).
_BSE_HOLIDAY_URL = ""  # unused — kept for reference

_RESOURCES_DIR = Path(__file__).parents[2] / "resources" / "calendar"

_MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def _nse_cache_path(year: int) -> str:
    tmp = os.environ.get("TMPDIR", os.environ.get("TEMP", "/tmp"))
    return os.path.join(tmp, f"nse_holidays_{year}.json")


def _bse_cache_path(year: int) -> str:
    tmp = os.environ.get("TMPDIR", os.environ.get("TEMP", "/tmp"))
    return os.path.join(tmp, f"bse_holidays_{year}.json")


def _load_json_cache(path: str) -> list[str] | None:
    try:
        if not os.path.exists(path):
            return None
        if time.time() - os.path.getmtime(path) > _CACHE_TTL_SECONDS:
            return None
        with open(path) as f:
            data = json.load(f)
        return data.get("holidays", [])
    except Exception:
        return None


def _save_json_cache(path: str, holidays: list[str]) -> None:
    try:
        with open(path, "w") as f:
            json.dump({"holidays": holidays, "cached_at": time.time()}, f)
    except Exception as exc:
        logger.debug("Failed to write calendar cache %s: %s", path, exc)


def _load_static_bse_holidays(year: int) -> list[str]:
    """Load the on-disk BSE holiday fallback (resources/calendar/bse_YYYY.json)."""
    path = _RESOURCES_DIR / f"bse_{year}.json"
    if not path.exists():
        return []
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
        entries = raw if isinstance(raw, list) else raw.get("holidays", [])
        return sorted({e["date"] for e in entries if e.get("date")})
    except Exception as exc:
        logger.debug("Failed to load static BSE calendar %s: %s", path, exc)
        return []


# ---------------------------------------------------------------------------
# NSE JSON parser
# ---------------------------------------------------------------------------

def _parse_nse_holidays(body: dict, year: int) -> list[str]:
    """Parse NSE holiday-master JSON response. Extracts CM (equity) segment dates."""
    dates: set[str] = set()

    # Response structure: {"CM": [{"tradingDate": "01-Jan-2026", ...}, ...], "FO": [...], ...}
    for segment_key in ("CM", "EQ", "ALL", "TRADING"):
        segment = body.get(segment_key, [])
        if not isinstance(segment, list):
            continue
        for item in segment:
            if not isinstance(item, dict):
                continue
            raw = item.get("tradingDate") or item.get("date") or item.get("holidayDate") or ""
            if not raw:
                continue
            # Parse "DD-Mon-YYYY" format
            try:
                from datetime import datetime as _dt
                for fmt in ("%d-%b-%Y", "%d/%m/%Y", "%Y-%m-%d"):
                    try:
                        d = _dt.strptime(raw.strip(), fmt).date()
                        if d.year == year:
                            dates.add(d.isoformat())
                        break
                    except ValueError:
                        continue
            except Exception:
                pass

    # Fallback: if none found in CM/EQ, try root-level list
    if not dates and isinstance(body, list):
        for item in body:
            if isinstance(item, dict):
                raw = item.get("tradingDate") or item.get("date") or ""
                try:
                    from datetime import datetime as _dt
                    d = _dt.strptime(raw.strip(), "%d-%b-%Y").date()
                    if d.year == year:
                        dates.add(d.isoformat())
                except Exception:
                    pass

    return sorted(dates)


# ---------------------------------------------------------------------------
# BSE HTML parser
# ---------------------------------------------------------------------------

def _parse_bse_dates(html: str, year: int) -> list[str]:
    """Extract holiday dates from BSE HTML page."""
    dates: set[str] = set()

    # Try DD/MM/YYYY and DD-MM-YYYY
    for match in re.finditer(r"\b(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})\b", html):
        d, m, y = int(match.group(1)), int(match.group(2)), int(match.group(3))
        if y == year and 1 <= m <= 12 and 1 <= d <= 31:
            try:
                dates.add(date(y, m, d).isoformat())
            except ValueError:
                pass

    # Try DD Month YYYY
    for match in re.finditer(
        r"\b(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})\b", html, re.IGNORECASE
    ):
        d_raw, mon, y = int(match.group(1)), match.group(2).lower()[:3], int(match.group(3))
        m = _MONTH_MAP.get(mon)
        if m and y == year and 1 <= d_raw <= 31:
            try:
                dates.add(date(y, m, d_raw).isoformat())
            except ValueError:
                pass

    return sorted(dates)


# ---------------------------------------------------------------------------
# CalendarFetcher
# ---------------------------------------------------------------------------

_KITE_INSTRUMENTS_URL = "https://api.kite.trade/instruments"
_NFO_INDEX_PREFIXES = ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY")

# Map NFO trading-symbol prefix → calendar key
_NFO_INDEX_MAP = {
    "NIFTY":      "nifty",
    "BANKNIFTY":  "banknifty",
    "FINNIFTY":   "finnifty",
    "MIDCPNIFTY": "midcap_nifty",
}


def _zerodha_expiries_cache_path() -> str:
    tmp = os.environ.get("TMPDIR", os.environ.get("TEMP", "/tmp"))
    return os.path.join(tmp, "zerodha_nse_expiries.json")


def _load_expiries_cache() -> dict | None:
    path = _zerodha_expiries_cache_path()
    try:
        if not os.path.exists(path):
            return None
        if time.time() - os.path.getmtime(path) > _CACHE_TTL_SECONDS:
            return None
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def _save_expiries_cache(expiries: dict) -> None:
    path = _zerodha_expiries_cache_path()
    try:
        with open(path, "w") as f:
            json.dump(expiries, f)
    except Exception as exc:
        logger.debug("Failed to save expiries cache: %s", exc)


class CalendarFetcher:
    """Fetch and cache NSE + BSE holiday calendars."""

    async def fetch_nse_expiries_from_zerodha(self) -> dict:
        """Parse NFO instruments CSV to get upcoming expiry dates per index.

        Returns dict keyed by calendar index name:
          {"nifty": ["2026-07-09", "2026-07-16", ...], "banknifty": [...], ...}

        Uses the enctoken from the active broker session. Returns {} if not
        authenticated or if the fetch fails — caller falls back to algorithmic.
        """
        cached = _load_expiries_cache()
        if cached is not None:
            return cached

        try:
            from src.broker import get_broker
            broker = get_broker()
            enctoken = broker.get_enctoken() if broker else None
            if not enctoken:
                return {}

            headers = {
                "Authorization": f"enctoken {enctoken}",
                "X-Kite-Version": "3",
            }
            with httpx.Client(timeout=15) as client:
                r = client.get(
                    _KITE_INSTRUMENTS_URL,
                    headers=headers,
                    params={"exchange": "NFO"},
                )
            if r.status_code != 200:
                logger.debug("Zerodha instruments fetch returned %d", r.status_code)
                return {}

            import csv as _csv
            import io as _io
            today = date.today()
            expiries: dict[str, set[str]] = {k: set() for k in _NFO_INDEX_MAP.values()}

            reader = _csv.DictReader(_io.StringIO(r.text))
            for row in reader:
                tradingsymbol = (row.get("tradingsymbol") or "").upper()
                instrument_type = (row.get("instrument_type") or "").upper()
                expiry_raw = (row.get("expiry") or "").strip()

                if instrument_type not in ("FUT", "CE", "PE"):
                    continue
                if not expiry_raw:
                    continue

                # Match prefix
                matched_key = None
                for prefix, key in _NFO_INDEX_MAP.items():
                    if tradingsymbol.startswith(prefix):
                        matched_key = key
                        break
                if not matched_key:
                    continue

                # Parse expiry date
                try:
                    exp_date = date.fromisoformat(expiry_raw)
                except ValueError:
                    try:
                        from datetime import datetime as _dt
                        exp_date = _dt.strptime(expiry_raw, "%d-%b-%Y").date()
                    except ValueError:
                        continue

                if exp_date >= today:
                    expiries[matched_key].add(exp_date.isoformat())

            result = {k: sorted(v) for k, v in expiries.items() if v}
            if result:
                _save_expiries_cache(result)
            return result

        except Exception as exc:
            logger.debug("fetch_nse_expiries_from_zerodha failed: %s", exc)
            return {}

    async def fetch_nse_holidays(self, year: int) -> list[str]:
        """Return NSE trading holidays for `year` as sorted ISO date strings."""
        cache_path = _nse_cache_path(year)
        cached = _load_json_cache(cache_path)
        if cached is not None:
            return cached

        # Try live JSON API
        try:
            with httpx.Client(timeout=10, follow_redirects=True) as client:
                r = client.get(_NSE_HOLIDAY_URL, headers=_NSE_HEADERS)
            if r.status_code == 200:
                body = r.json()
                dates = _parse_nse_holidays(body, year)
                if dates:
                    _save_json_cache(cache_path, dates)
                    return dates
                logger.warning("NSE holiday API returned 0 dates for %d", year)
            else:
                logger.warning(
                    "NSE holiday API returned status %d for %d: %s",
                    r.status_code, year, r.text[:200],
                )
        except Exception as exc:
            logger.warning("NSE holiday live fetch failed: %s", exc)

        # Fallback: existing NSEOfficialProvider (uses same API with more robust parsing)
        try:
            from src.providers.calendar.nse_provider import NSEOfficialProvider
            provider = NSEOfficialProvider(year=year)
            result = provider.fetch()
            if result and result.data:
                holidays = sorted(d.isoformat() for d in result.data)
                _save_json_cache(cache_path, holidays)
                return holidays
        except Exception as exc:
            logger.warning("NSEOfficialProvider fallback failed for %d: %s", year, exc)

        # Last resort: JSON calendar files already on disk
        try:
            from src.providers.calendar.json_provider import JSONCalendarProvider
            meta = JSONCalendarProvider().load(year)
            stored = meta.get("holidays", {})
            holidays = sorted(d.isoformat() for d in stored)
            if holidays:
                return holidays
        except Exception as exc:
            logger.debug("JSON provider fallback also failed: %s", exc)

        return []

    async def fetch_bse_holidays(self, year: int) -> list[str]:
        """Return BSE trading holidays for `year` as sorted ISO date strings.

        BSE holiday page is a JS-rendered Angular SPA — live HTML scrape
        returns no dates. We go straight to the static JSON fallback, then
        NSE holidays (95%+ overlap) as last resort.
        """
        cache_path = _bse_cache_path(year)
        cached = _load_json_cache(cache_path)
        if cached is not None:
            return cached

        # Primary: static on-disk BSE calendar (resources/calendar/bse_YYYY.json)
        static = _load_static_bse_holidays(year)
        if static:
            _save_json_cache(cache_path, static)
            return static

        # Fallback: NSE holidays (95%+ overlap)
        logger.warning("No static BSE calendar for %d — falling back to NSE holidays", year)
        nse = await self.fetch_nse_holidays(year)
        return nse

    async def get_combined_calendar(self, year: int) -> dict:
        """Return both NSE and BSE holidays with overlap/diff analysis."""
        nse = await self.fetch_nse_holidays(year)
        bse = await self.fetch_bse_holidays(year)
        nse_set = set(nse)
        bse_set = set(bse)
        return {
            "nse_holidays": nse,
            "bse_holidays": bse,
            "common_holidays": sorted(nse_set & bse_set),
            "nse_only": sorted(nse_set - bse_set),
            "bse_only": sorted(bse_set - nse_set),
        }

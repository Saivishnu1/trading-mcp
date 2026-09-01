"""
Phase 24A — Market calendar service (provider-backed).

get_market_calendar() is the canonical source for:
  - today's trading status
  - nearest option expiry per index
  - days to expiry
  - upcoming holidays
  - next trading day

Holiday resolution (via CalendarProviderChain):
  1. JSONCalendarProvider  — resources/calendar/YYYY.json (with in-memory TTL cache)
  2. EmergencyCalendarProvider — minimal hardcoded fallback

Expiry resolution order:
  1. Options service (live expiry dates from NSE)
  2. Algorithmic fallback (compute next scheduled expiry day)
"""
from __future__ import annotations

import json as _json_mod
import os as _os_mod
import time as _time_mod
from datetime import date, datetime, timedelta
from datetime import time as _time
from typing import Optional

import pytz as _pytz

from src.providers.calendar.chain import get_calendar_provider, reset_calendar_provider

_IST = _pytz.timezone("Asia/Kolkata")
_MARKET_OPEN = _time(9, 15)
_MARKET_CLOSE = _time(15, 30)


def _load_zerodha_expiries_cache() -> dict:
    """Read the Zerodha expiry cache written by CalendarFetcher — sync, no network."""
    tmp = _os_mod.environ.get("TMPDIR", _os_mod.environ.get("TEMP", "/tmp"))
    path = _os_mod.path.join(tmp, "zerodha_nse_expiries.json")
    try:
        if not _os_mod.path.exists(path):
            return {}
        if _time_mod.time() - _os_mod.path.getmtime(path) > 86400:
            return {}
        with open(path) as f:
            return _json_mod.load(f)
    except Exception:
        return {}

# ---------------------------------------------------------------------------
# Expiry day-of-week per index (0=Mon … 6=Sun)
# ---------------------------------------------------------------------------

_EXPIRY_WEEKDAY: dict[str, int] = {
    "nifty":        1,  # Tuesday (NSE moved from Thursday, effective 2026)
    "banknifty":    1,  # Tuesday (last Tuesday of month)
    "finnifty":     1,  # Tuesday (last Tuesday of month)
    "midcap_nifty": 1,  # Tuesday (last Tuesday of month)
    "sensex":       3,  # Thursday (BSE weekly)
    "bankex":       3,  # Thursday (BSE, last Thursday of month)
}

# BSE indices that expire on Thursdays
_BSE_EXPIRY_INDICES = {"sensex", "bankex"}

# Indices whose weekly contract was withdrawn (SEBI weekly-expiry rationalization,
# effective Nov 2024) — only NIFTY (NSE) and SENSEX (BSE) retain a weekly series.
# These indices trade monthly contracts only, so their nearest expiry IS the
# last occurrence of their weekday in the current/next month.
_MONTHLY_ONLY_INDICES = {"banknifty", "finnifty", "midcap_nifty", "bankex"}

# NSE/BSE session times (IST, 24h)
_SESSION_TIMES = {
    "nse": {
        "pre_open_start": "09:00",
        "pre_open_end": "09:15",
        "open": "09:15",
        "close": "15:30",
    },
    "bse": {
        "pre_open_start": "09:00",
        "pre_open_end": "09:15",
        "open": "09:15",
        "close": "15:30",
    },
}

# Updated on each get_market_calendar() call — read by get_calendar_health()
_last_expiry_source: str = "algorithmic"


# ---------------------------------------------------------------------------
# Backward-compat reset helper (used by tests)
# ---------------------------------------------------------------------------

def _reset_holiday_cache() -> None:
    """Reset provider chain and expiry source state — for tests only."""
    global _last_expiry_source
    reset_calendar_provider()
    _last_expiry_source = "algorithmic"


# ---------------------------------------------------------------------------
# Calendar helpers
# ---------------------------------------------------------------------------

def _is_holiday(d: date) -> bool:
    result = get_calendar_provider().fetch()
    return d in result.data


def _is_trading_day(d: date) -> bool:
    """Return True if `d` is a weekday and not an NSE holiday."""
    return d.weekday() < 5 and not _is_holiday(d)


def _next_trading_day(from_date: date) -> date:
    """Return the next trading day strictly after `from_date`."""
    d = from_date + timedelta(days=1)
    while not _is_trading_day(d):
        d += timedelta(days=1)
    return d


def _last_weekday_of_month(year: int, month: int, weekday: int) -> date:
    """Return the date of the last occurrence of `weekday` (0=Mon…6=Sun) in year/month."""
    if month == 12:
        first_of_next = date(year + 1, 1, 1)
    else:
        first_of_next = date(year, month + 1, 1)
    last_day = first_of_next - timedelta(days=1)
    offset = (last_day.weekday() - weekday) % 7
    return last_day - timedelta(days=offset)


def _nearest_monthly_expiry(index: str, from_date: date) -> Optional[date]:
    """Compute the nearest last-weekday-of-month expiry for a monthly-only index."""
    weekday = _EXPIRY_WEEKDAY.get(index.lower())
    if weekday is None:
        return None

    candidate = _last_weekday_of_month(from_date.year, from_date.month, weekday)
    if candidate < from_date:
        month = from_date.month + 1
        year = from_date.year
        if month > 12:
            month = 1
            year += 1
        candidate = _last_weekday_of_month(year, month, weekday)

    while _is_holiday(candidate) or candidate.weekday() >= 5:
        candidate -= timedelta(days=1)

    return candidate


def _nearest_expiry_algorithmic(index: str, from_date: date) -> Optional[date]:
    """Compute the nearest expiry for an index — weekly for NIFTY/SENSEX
    (the two indices retaining a weekly series), monthly (last weekday of
    month) for all other indices."""
    idx = index.lower()
    if idx in _MONTHLY_ONLY_INDICES:
        return _nearest_monthly_expiry(idx, from_date)

    weekday = _EXPIRY_WEEKDAY.get(idx)
    if weekday is None:
        return None

    days_ahead = (weekday - from_date.weekday()) % 7
    candidate = from_date + timedelta(days=days_ahead)

    while _is_holiday(candidate) or candidate.weekday() >= 5:
        candidate -= timedelta(days=1)

    return candidate


def _upcoming_holidays(from_date: date, days_ahead: int = 30) -> list[dict]:
    result = get_calendar_provider().fetch()
    holidays = result.data
    end = from_date + timedelta(days=days_ahead)
    return [
        {"date": d.isoformat(), "name": name}
        for d, name in sorted(holidays.items())
        if from_date < d <= end
    ]


def _trading_days_remaining_this_week(today: date) -> int:
    """Count trading days from today (inclusive) through Friday of this week."""
    count = 0
    friday = today + timedelta(days=(4 - today.weekday()) % 7)
    d = today
    while d <= friday:
        if _is_trading_day(d):
            count += 1
        d += timedelta(days=1)
    return count


def _expiry_days_this_week(today: date) -> list[str]:
    """Return weekday names of expiry days occurring this week, in chronological order."""
    monday = today - timedelta(days=today.weekday())
    friday = monday + timedelta(days=4)
    expiry_weekdays = set(_EXPIRY_WEEKDAY.values())
    seen: set[str] = set()
    days: list[str] = []
    d = monday
    while d <= friday:
        name = d.strftime("%A")
        if d.weekday() in expiry_weekdays and _is_trading_day(d) and name not in seen:
            days.append(name)
            seen.add(name)
        d += timedelta(days=1)
    return days


def _live_expiries() -> dict[str, str]:
    """Pull nearest expiry dates from live sources.

    Priority 1 (NSE + BSE): Zerodha instruments CSV — covers NFO and BFO,
      no auth required, most accurate source for monthly-only indices.
    Priority 2 (NSE gaps): NSE option chain service.
    Priority 3 (BSE gaps): BSE options service available_expiries.
    """
    results: dict[str, str] = {}
    today = _today_ist()

    # Priority 1: Zerodha instruments CSV — NFO + BFO, no enctoken needed
    try:
        import asyncio

        from src.calendar import CalendarFetcher
        fetcher = CalendarFetcher()
        try:
            loop = asyncio.get_event_loop()
            if not loop.is_running():
                zd_expiries = asyncio.run(fetcher.fetch_all_expiries_from_zerodha())
            else:
                zd_expiries = _load_zerodha_expiries_cache()
        except RuntimeError:
            zd_expiries = asyncio.run(fetcher.fetch_all_expiries_from_zerodha())

        for idx, dates in (zd_expiries or {}).items():
            if dates:
                upcoming = [d for d in dates if d >= today.isoformat()]
                if upcoming:
                    results[idx] = upcoming[0]
    except Exception:
        pass

    # Priority 2: NSE option chain — fills any NSE gaps
    try:
        from src.options.service import get_options_service
        svc = get_options_service()
        for index, nse_sym in [("nifty", "NIFTY"), ("banknifty", "BANKNIFTY"),
                                ("finnifty", "FINNIFTY"), ("midcap_nifty", "MIDCPNIFTY")]:
            if index in results:
                continue
            try:
                meta = svc.get_option_chain(nse_sym)
                expiry_dates = meta.get("records", {}).get("expiryDates", [])
                if expiry_dates:
                    results[index] = expiry_dates[0]
            except Exception:
                pass
    except Exception:
        pass

    # Priority 3: BSE options service — fills any BSE gaps
    try:
        from src.options.bse_service import get_bse_options_service
        bse_svc = get_bse_options_service()
        for index, bse_sym in [("sensex", "SENSEX"), ("bankex", "BANKEX")]:
            if index in results:
                continue
            try:
                expiries = bse_svc.available_expiries(bse_sym)
                if expiries:
                    results[index] = expiries[0]
            except Exception:
                pass
    except Exception:
        pass

    return results


# ---------------------------------------------------------------------------
# Health accessor — reads provider chain state, no live API calls
# ---------------------------------------------------------------------------

def get_calendar_health() -> dict:
    """
    Return calendar data-source health.

    Status values:
      HEALTHY   — JSON calendar loaded fresh
      CACHED    — serving from in-memory TTL cache (normal operation)
      EMERGENCY — emergency hardcoded fallback in use (JSON files unavailable)
      FAILED    — all providers exhausted

    Extended fields (Phase 24B):
      version          — JSON file version ("YYYY.N") or None for old format
      source.runtime   — always "JSONCalendarProvider"
      source.refresh   — always "NSEOfficialProvider"
    """
    chain = get_calendar_provider()
    if chain.last_result is None:
        chain.fetch()  # Initialize so health reflects actual state
    chain_health = chain.health()
    chain_health["expiry_source"] = _last_expiry_source
    chain_health["version"] = chain.version()
    chain_health["source"] = {
        "runtime": "JSONCalendarProvider",
        "refresh": "NSEOfficialProvider",
    }
    return chain_health


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _fetch_bse_holiday_names(year: int) -> dict[str, str]:
    """Return BSE holidays as {iso_date: name} from static bse_YYYY.json."""
    import json as _json
    from pathlib import Path
    resources = Path(__file__).parents[2] / "resources" / "calendar"
    for fname in (f"bse_{year}.json", f"{year}.json"):
        path = resources / fname
        if not path.exists():
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                raw = _json.load(fh)
            entries = raw if isinstance(raw, list) else raw.get("holidays", [])
            return {e["date"]: e.get("name", "BSE Holiday") for e in entries if e.get("date")}
        except Exception:
            pass
    return {}


def _fetch_bse_holidays_sync(year: int) -> list[str]:
    """Return BSE holidays for the year — synchronous, no event loop needed.

    Resolution order:
      1. /tmp cache file (set by async CalendarFetcher on previous async call)
      2. Static resources/calendar/bse_YYYY.json (always available)
      3. Static resources/calendar/YYYY.json (NSE, 95%+ overlap)
    """
    import json as _json
    import os as _os
    import time as _time

    # Check /tmp cache written by async CalendarFetcher
    tmp = _os.environ.get("TMPDIR", _os.environ.get("TEMP", "/tmp"))
    cache_path = _os.path.join(tmp, f"bse_holidays_{year}.json")
    try:
        if _os.path.exists(cache_path):
            mtime = _os.path.getmtime(cache_path)
            if _time.time() - mtime < 86400:
                with open(cache_path) as f:
                    data = _json.load(f)
                cached = data.get("holidays", [])
                if cached:
                    return cached
    except Exception:
        pass

    # Static BSE calendar file
    from pathlib import Path
    resources = Path(__file__).parents[2] / "resources" / "calendar"
    for fname in (f"bse_{year}.json", f"{year}.json"):
        path = resources / fname
        if not path.exists():
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                raw = _json.load(fh)
            entries = raw if isinstance(raw, list) else raw.get("holidays", [])
            holidays = sorted(e["date"] for e in entries if e.get("date"))
            if holidays:
                return holidays
        except Exception:
            pass

    return []


def _today_ist() -> date:
    """IST calendar date — confirmed bug (2026-07-13): get_market_calendar()
    and _live_expiries() both used date.today() (the OS/process-local date,
    UTC on the Oracle VM). IST is UTC+5:30, so during IST 00:00-05:29 the
    UTC date is still "yesterday" — date.today() reports a day behind the
    real IST calendar date in that window, which is exactly what surfaced
    as get_market_calendar() reporting Sunday when it was already Monday
    IST. Mirrors the already-correct _today_ist() in
    src/monitor/repository.py / src/monitor/scheduler.py, just not
    previously applied here."""
    return datetime.now(_IST).date()


def is_market_session_open(calendar: dict | None = None) -> bool:
    """True if the NSE/BSE cash+F&O session is live right now: today is a
    trading day (not a weekend or holiday — via get_market_calendar()'s
    existing holiday/weekend detection, not re-derived here) and the
    current IST time falls within 09:15-15:30.

    Used to auto-flag order-placement requests as AMO (see
    OrderRequest.is_amo) instead of letting a regular-session order hit
    INDstocks outside trading hours, which surfaces as an opaque 512
    Internal Server Error rather than a clean rejection (confirmed
    2026-07-12 against a real after-hours order attempt).

    Pass an already-fetched get_market_calendar() dict via `calendar` to
    avoid a second fetch when the caller already has one.
    """
    cal = calendar if calendar is not None else get_market_calendar()
    if not cal.get("today", {}).get("is_trading_day", True):
        return False
    now = datetime.now(_IST).time()
    return _MARKET_OPEN <= now <= _MARKET_CLOSE


def get_market_calendar() -> dict:
    """Return the canonical market calendar for today."""
    global _last_expiry_source

    today = _today_ist()
    cal_result = get_calendar_provider().fetch()
    holidays = cal_result.data
    holiday_name = holidays.get(today)
    is_holiday_today = holiday_name is not None
    is_weekend = today.weekday() >= 5
    is_trading = not is_holiday_today and not is_weekend

    # Fetch BSE holidays for current year (cached after first call)
    bse_holidays = _fetch_bse_holidays_sync(today.year)
    bse_holiday_today = today.isoformat() in bse_holidays
    is_bse_trading = not bse_holiday_today and not is_weekend

    # Expiries — live first, algorithmic fallback per missing index
    live = _live_expiries()
    expiries: dict[str, str] = {}
    days_to_expiry: dict[str, int] = {}
    per_index_expiry_source: dict[str, str] = {}

    monthly_expiries: dict[str, str] = {}
    from datetime import datetime as _dt
    for idx in ("nifty", "banknifty", "finnifty", "midcap_nifty", "sensex", "bankex"):
        exp_date: Optional[date] = None
        src = "algorithmic"

        # Always compute monthly expiry for reference
        monthly_date = _nearest_monthly_expiry(idx, today)
        if monthly_date:
            monthly_expiries[idx] = monthly_date.isoformat()

        if idx in live:
            exp_str = live[idx]
            for fmt in ("%d-%b-%Y", "%d %b %Y", "%Y-%m-%d"):
                try:
                    exp_date = _dt.strptime(exp_str.strip(), fmt).date()
                    break
                except ValueError:
                    continue
            if exp_date:
                src = "live"

        if exp_date is None:
            # Monthly-only indices: always use last-weekday-of-month, not weekly
            if idx in _MONTHLY_ONLY_INDICES:
                exp_date = monthly_date
            else:
                exp_date = _nearest_expiry_algorithmic(idx, today)
            src = "algorithmic"

        if exp_date:
            expiries[idx] = exp_date.isoformat()
            days_to_expiry[idx] = (exp_date - today).days
        per_index_expiry_source[idx] = src

    agg_expiry_source = "live" if any(v == "live" for v in per_index_expiry_source.values()) else "algorithmic"
    _last_expiry_source = agg_expiry_source

    # Build upcoming holidays for both exchanges (90-day window matches top-level nse_holidays)
    nse_upcoming = _upcoming_holidays(today, days_ahead=90)
    # NSE name lookup — live-refreshed from NSE API, covers 95%+ of BSE holidays too
    nse_name_map = {h["date"]: h["name"] for h in nse_upcoming}
    bse_upcoming = []
    if bse_holidays:
        end = today + timedelta(days=90)
        for h in bse_holidays:
            try:
                h_date = date.fromisoformat(h)
                if today < h_date <= end:
                    name = nse_name_map.get(h) or _fetch_bse_holiday_names(today.year).get(h, "BSE Holiday")
                    bse_upcoming.append({"date": h, "name": name})
            except ValueError:
                pass

    # Session active status — IST-aware (matches is_market_session_open()/
    # meta.is_market_hours()). Computed inline rather than by calling
    # is_market_session_open() to avoid recursion (that function calls
    # get_market_calendar() when not passed one).
    now_ist_time = datetime.now(_IST).time()
    in_session_hours = _MARKET_OPEN <= now_ist_time <= _MARKET_CLOSE
    session_active = is_trading and in_session_hours
    bse_session_active = is_bse_trading and in_session_hours

    calendar_source = "live" if any(v == "live" for v in per_index_expiry_source.values()) else "cached"
    if not bse_holidays:
        calendar_source = "fallback"

    return {
        # --- Top-level flat fields (Fix 5 spec) ---
        "today_date": today.isoformat(),
        "nse_session": "09:15-15:30 IST",
        "bse_session": "09:15-15:30 IST",
        "nse_session_active": session_active,
        "bse_session_active": bse_session_active,
        "nse_holidays": [h["date"] for h in _upcoming_holidays(today, days_ahead=90)],
        "bse_holidays": sorted(
            h for h in bse_holidays
            if h > today.isoformat()
            and h <= (today + timedelta(days=90)).isoformat()
        ),
        "nse_only_holidays": sorted(
            set(h["date"] for h in nse_upcoming) - set(h["date"] for h in bse_upcoming)
        ),
        "bse_only_holidays": sorted(
            set(h["date"] for h in bse_upcoming) - set(h["date"] for h in nse_upcoming)
        ),
        "nse_expiries": {
            "nifty_weekly":         "Tuesday",
            "nifty_monthly":        "last Tuesday of month",
            "banknifty_monthly":    "last Tuesday of month",
            "finnifty_monthly":     "last Tuesday of month",
            "midcap_nifty_monthly": "last Tuesday of month",
        },
        "bse_expiries": {
            "sensex_weekly":  "Thursday",
            "sensex_monthly": "last Thursday of month",
            "bankex_monthly": "last Thursday of month",
        },
        "next_nse_expiry": expiries.get("nifty"),
        "next_bse_sensex_expiry": expiries.get("sensex"),
        "next_bse_bankex_expiry": expiries.get("bankex"),
        "calendar_source": calendar_source,
        # --- Detailed nested blocks (backward compat) ---
        "today": {
            "date": today.isoformat(),
            "day": today.strftime("%A"),
            "is_trading_day": is_trading,
            "is_holiday": is_holiday_today,
            "holiday_name": holiday_name,
        },
        "nse": {
            "is_trading_day": is_trading,
            "is_holiday": is_holiday_today,
            "holiday_name": holiday_name,
            "session_times": _SESSION_TIMES["nse"],
            "session_active": session_active,
            "upcoming_holidays": nse_upcoming,
        },
        "bse": {
            "is_trading_day": is_bse_trading,
            "is_holiday": bse_holiday_today,
            "session_times": _SESSION_TIMES["bse"],
            "session_active": bse_session_active,
            "upcoming_holidays": bse_upcoming,
        },
        "expiries": expiries,
        "monthly_expiries": monthly_expiries,
        "days_to_expiry": days_to_expiry,
        "upcoming_holidays": nse_upcoming,
        "next_trading_day": _next_trading_day(today).isoformat(),
        "week_summary": {
            "trading_days_remaining": _trading_days_remaining_this_week(today),
            "expiry_days_this_week": _expiry_days_this_week(today),
        },
        "source_meta": {
            **cal_result.as_source_meta(),
            "expiry_source": agg_expiry_source,
            "expiry_source_per_index": per_index_expiry_source,
            "provider_meta": cal_result.as_provider_meta(),
        },
    }

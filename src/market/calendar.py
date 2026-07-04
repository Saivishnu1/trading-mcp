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

from datetime import date, timedelta
from typing import Optional

from src.providers.calendar.chain import get_calendar_provider, reset_calendar_provider

# ---------------------------------------------------------------------------
# Expiry day-of-week per index (0=Mon … 6=Sun)
# ---------------------------------------------------------------------------

_EXPIRY_WEEKDAY: dict[str, int] = {
    "nifty":        3,  # Thursday
    "banknifty":    2,  # Wednesday
    "finnifty":     1,  # Tuesday
    "midcap_nifty": 3,  # Thursday (monthly)
    "sensex":       3,  # Thursday (BSE)
    "bankex":       3,  # Thursday (BSE)
}

# BSE indices that expire on Thursdays
_BSE_EXPIRY_INDICES = {"sensex", "bankex"}

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


def _nearest_expiry_algorithmic(index: str, from_date: date) -> Optional[date]:
    """Compute the nearest weekly/monthly expiry for an index."""
    weekday = _EXPIRY_WEEKDAY.get(index.lower())
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
    """Try to pull nearest expiry dates from NSE options service + INDmoney for BSE."""
    results: dict[str, str] = {}

    # NSE indices via options service
    try:
        from src.options.service import get_options_service
        svc = get_options_service()
        for index, nse_sym in [("nifty", "NIFTY"), ("banknifty", "BANKNIFTY"),
                                ("finnifty", "FINNIFTY"), ("midcap_nifty", "MIDCPNIFTY")]:
            try:
                meta = svc.get_option_chain(nse_sym)
                expiry_dates = meta.get("records", {}).get("expiryDates", [])
                if expiry_dates:
                    results[index] = expiry_dates[0]
            except Exception:
                pass
    except Exception:
        pass

    # BSE indices via INDmoney /option-chain-symbols
    import os
    token = os.environ.get("INDSTOCKS_TOKEN", "")
    if token:
        try:
            import httpx
            from datetime import datetime as _dt
            today = date.today()
            for idx, sym in [("sensex", "SENSEX"), ("bankex", "BANKEX")]:
                try:
                    with httpx.Client(timeout=8) as client:
                        r = client.get(
                            "https://api.indstocks.com/option-chain-symbols",
                            headers={"Authorization": token, "Content-Type": "application/json"},
                            params={"symbol": sym},
                        )
                    if r.status_code != 200:
                        continue
                    body = r.json()
                    # Response may be a list of expiry date strings or a dict with expiry list
                    expiry_list: list = []
                    if isinstance(body, list):
                        expiry_list = body
                    elif isinstance(body, dict):
                        expiry_list = (
                            body.get("expiry_dates")
                            or body.get("expiryDates")
                            or body.get("data", [])
                        )
                    # Find nearest upcoming expiry
                    nearest = None
                    for raw in expiry_list:
                        exp_date = None
                        for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%d/%m/%Y"):
                            try:
                                exp_date = _dt.strptime(str(raw).strip(), fmt).date()
                                break
                            except ValueError:
                                continue
                        if exp_date and exp_date >= today:
                            if nearest is None or exp_date < nearest:
                                nearest = exp_date
                    if nearest:
                        results[idx] = nearest.isoformat()
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

def _fetch_bse_holidays_sync(year: int) -> list[str]:
    """Synchronous wrapper to fetch BSE holidays for the calendar response."""
    try:
        import asyncio
        from src.calendar import CalendarFetcher
        fetcher = CalendarFetcher()
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Inside async context — schedule but return empty to avoid deadlock
                return []
        except RuntimeError:
            loop = asyncio.new_event_loop()
        return asyncio.run(fetcher.fetch_bse_holidays(year))
    except Exception:
        return []


def get_market_calendar() -> dict:
    """Return the canonical market calendar for today."""
    global _last_expiry_source

    today = date.today()
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

    for idx in ("nifty", "banknifty", "finnifty", "midcap_nifty", "sensex", "bankex"):
        if idx in live:
            exp_str = live[idx]
            exp_date: Optional[date] = None
            try:
                from datetime import datetime as _dt
                for fmt in ("%d-%b-%Y", "%Y-%m-%d"):
                    try:
                        exp_date = _dt.strptime(exp_str, fmt).date()
                        break
                    except ValueError:
                        continue
            except Exception:
                exp_date = None
            src = "live"
        else:
            exp_date = _nearest_expiry_algorithmic(idx, today)
            src = "algorithmic"

        if exp_date:
            expiries[idx] = exp_date.isoformat()
            days_to_expiry[idx] = (exp_date - today).days
        per_index_expiry_source[idx] = src

    agg_expiry_source = "live" if any(v == "live" for v in per_index_expiry_source.values()) else "algorithmic"
    _last_expiry_source = agg_expiry_source

    # Build upcoming holidays for both exchanges
    nse_upcoming = _upcoming_holidays(today)
    bse_upcoming = []
    if bse_holidays:
        end = today + timedelta(days=30)
        for h in bse_holidays:
            try:
                h_date = date.fromisoformat(h)
                if today < h_date <= end:
                    bse_upcoming.append({"date": h, "name": "BSE Holiday"})
            except ValueError:
                pass

    # Session active status (naive — doesn't check market hours, just trading day)
    from datetime import datetime as _dt_cls
    now = _dt_cls.now()
    hour_min = now.hour * 60 + now.minute
    market_open_min = 9 * 60 + 15
    market_close_min = 15 * 60 + 30
    session_active = (
        is_trading
        and market_open_min <= hour_min <= market_close_min
    )
    bse_session_active = (
        is_bse_trading
        and market_open_min <= hour_min <= market_close_min
    )

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
        "nse_holidays": [h["date"] for h in nse_upcoming],
        "bse_holidays": [h["date"] for h in bse_upcoming],
        "nse_only_holidays": sorted(
            set(h["date"] for h in nse_upcoming) - set(h["date"] for h in bse_upcoming)
        ),
        "bse_only_holidays": sorted(
            set(h["date"] for h in bse_upcoming) - set(h["date"] for h in nse_upcoming)
        ),
        "nse_expiries": {
            "nifty_weekly":     "Thursday",
            "banknifty_weekly": "Wednesday",
            "finnifty_weekly":  "Tuesday",
            "nifty_monthly":    "last Thursday of month",
        },
        "bse_expiries": {
            "sensex_weekly":   "Thursday",
            "bankex_weekly":   "Thursday",
            "sensex_monthly":  "last Thursday of month",
            "bankex_monthly":  "last Thursday of month",
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

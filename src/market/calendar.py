"""
Phase 23 — Market calendar service.

get_market_calendar() is the canonical source for:
  - today's trading status
  - nearest option expiry per index
  - days to expiry
  - upcoming holidays
  - next trading day

Holiday resolution order:
  1. Holiday provider (external source — no live provider exists yet)
  2. Holiday cache   (populated from provider on first successful call)
  3. Hardcoded fallback (_NSE_HOLIDAYS_2026)

Expiry resolution order:
  1. Options service (live expiry dates from NSE)
  2. Algorithmic fallback (compute next scheduled expiry day)
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

# ---------------------------------------------------------------------------
# 2026 NSE holiday list — FINAL FALLBACK ONLY
# Source: NSE circular. Accurate as of June 2026.
# ---------------------------------------------------------------------------

_NSE_HOLIDAYS_2026: dict[date, str] = {
    date(2026, 1, 26): "Republic Day",
    date(2026, 2, 26): "Maha Shivratri",
    date(2026, 3, 17): "Holi",
    date(2026, 3, 30): "Id-Ul-Fitr (Ramadan Eid)",
    date(2026, 4, 2):  "Ram Navami",
    date(2026, 4, 3):  "Good Friday",
    date(2026, 4, 14): "Dr. Baba Saheb Ambedkar Jayanti",
    date(2026, 5, 1):  "Maharashtra Day",
    date(2026, 6, 17): "Bakri Id",
    date(2026, 8, 15): "Independence Day",
    date(2026, 8, 27): "Ganesh Chaturthi",
    date(2026, 9, 16): "Milad-un-Nabi (Id-E-Milad)",
    date(2026, 10, 2): "Mahatma Gandhi Jayanti",
    date(2026, 10, 20): "Dussehra",
    date(2026, 11, 2): "Diwali (Laxmi Pujan)",
    date(2026, 11, 3): "Diwali (Balipratipada)",
    date(2026, 11, 25): "Gurunanak Jayanti",
    date(2026, 12, 25): "Christmas",
}

# ---------------------------------------------------------------------------
# Expiry day-of-week per index (0=Mon … 6=Sun)
# ---------------------------------------------------------------------------

_EXPIRY_WEEKDAY: dict[str, int] = {
    "nifty":        3,  # Thursday
    "banknifty":    2,  # Wednesday
    "finnifty":     1,  # Tuesday
    "midcap_nifty": 3,  # Thursday (monthly)
    "sensex":       4,  # Friday
}

# ---------------------------------------------------------------------------
# Holiday provider → cache → fallback architecture
# ---------------------------------------------------------------------------

# Module-level state — reset by tests via _reset_holiday_cache()
_holiday_cache: dict[date, str] | None = None
_holidays_loaded: bool = False
_holiday_source: str = "not_configured"

# Updated on each get_market_calendar() call — read by get_calendar_health()
_last_expiry_source: str = "algorithmic"


def _holiday_provider() -> dict[date, str] | None:
    """
    External holiday provider interface.

    No live holiday API is integrated — this stub always returns None.
    A real implementation would fetch from NSE/Bombay Exchange APIs here.
    When a provider is available, populate this function and the cache
    architecture will automatically prefer live data.
    """
    return None


def _load_holidays() -> tuple[dict[date, str], str]:
    """
    Return (holidays_dict, source) with provider → cache → fallback resolution.

    Source values:
      "provider"       — live provider responded with data
      "cache"          — prior provider data still in cache
      "not_configured" — provider intentionally not configured (returned None)
      "offline"        — provider raised an exception (configured but unavailable)

    Provider is attempted exactly once per process (no retry storm).
    """
    global _holiday_cache, _holidays_loaded, _holiday_source

    if _holidays_loaded:
        return (_holiday_cache if _holiday_cache is not None else _NSE_HOLIDAYS_2026), _holiday_source

    _holidays_loaded = True

    # 1. Try provider
    _provider_raised = False
    try:
        data = _holiday_provider()
        if data is not None:
            _holiday_cache = data
            _holiday_source = "provider"
            return _holiday_cache, "provider"
        # Provider returned None — intentionally not configured
        _pending_source = "not_configured"
    except Exception:
        # Provider raised — configured but unavailable
        _provider_raised = True
        _pending_source = "offline"

    # 2. Cache still valid from a prior session bootstrap (rare path)
    if _holiday_cache is not None:
        _holiday_source = "cache"
        return _holiday_cache, "cache"

    # 3. Hardcoded fallback — source reflects WHY we fell back
    _holiday_source = _pending_source
    return _NSE_HOLIDAYS_2026, _holiday_source


def _reset_holiday_cache() -> None:
    """Reset module state — for tests only."""
    global _holiday_cache, _holidays_loaded, _holiday_source, _last_expiry_source
    _holiday_cache = None
    _holidays_loaded = False
    _holiday_source = "not_configured"
    _last_expiry_source = "algorithmic"


# ---------------------------------------------------------------------------
# Calendar helpers
# ---------------------------------------------------------------------------

def _is_holiday(d: date) -> bool:
    holidays, _ = _load_holidays()
    return d in holidays


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

    # Find the next occurrence of the expiry weekday (including today)
    days_ahead = (weekday - from_date.weekday()) % 7
    candidate = from_date + timedelta(days=days_ahead)

    # If the candidate is a holiday, roll back to the preceding trading day
    while _is_holiday(candidate) or candidate.weekday() >= 5:
        candidate -= timedelta(days=1)

    return candidate


def _upcoming_holidays(from_date: date, days_ahead: int = 30) -> list[dict]:
    holidays, _ = _load_holidays()
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
    """Try to pull nearest expiry dates from the live options service."""
    try:
        from src.options.service import get_options_service
        svc = get_options_service()

        results: dict[str, str] = {}
        for index, nse_sym in [("nifty", "NIFTY"), ("banknifty", "BANKNIFTY"),
                                ("finnifty", "FINNIFTY"), ("midcap_nifty", "MIDCPNIFTY")]:
            try:
                meta = svc.get_option_chain(nse_sym)
                expiry_dates = meta.get("records", {}).get("expiryDates", [])
                if expiry_dates:
                    results[index] = expiry_dates[0]
            except Exception:
                pass
        return results
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Health accessor — read module-level state, no API calls
# ---------------------------------------------------------------------------

_CALENDAR_HEALTH_STATUS: dict[str, str] = {
    "provider":       "HEALTHY",
    "cache":          "CACHED",
    "not_configured": "CONFIGURATION_LIMITED",
    "offline":        "OFFLINE",
}

_CALENDAR_HEALTH_REASON: dict[str, str | None] = {
    "provider":       None,
    "cache":          "Holiday provider unavailable; serving from previously populated cache.",
    "not_configured": "No live holiday provider configured; using hardcoded 2026 list. System functioning normally.",
    "offline":        "Holiday provider is offline; using hardcoded fallback.",
}

_CALENDAR_HEALTH_SEVERITY: dict[str, str] = {
    "HEALTHY":              "INFO",
    "CONFIGURATION_LIMITED": "INFO",
    "CACHED":               "WARNING",
    "OFFLINE":              "WARNING",
    "FAILED":               "ERROR",
}

_CALENDAR_HEALTH_ACTION: dict[str, str | None] = {
    "HEALTHY":               None,
    "CONFIGURATION_LIMITED": "System functioning normally. Configure a live provider to enable automatic holiday updates.",
    "CACHED":                "Monitor provider connectivity. Cache will expire if the process restarts without a provider.",
    "OFFLINE":               "Check holiday provider connectivity. Hardcoded list used until provider recovers.",
    "FAILED":                "Calendar service unavailable. Check logs immediately.",
}


def get_calendar_health() -> dict:
    """
    Return calendar data-source health without making live API calls.

    Status values:
      HEALTHY              — live provider responding
      CONFIGURATION_LIMITED — no provider configured; fallback expected; normal operation
      CACHED               — cache serving after provider failure
      OFFLINE              — provider raised an exception; hardcoded fallback in use
      FAILED               — no calendar data available (should not occur in practice)
    """
    _, h_source = _load_holidays()
    e_source = _last_expiry_source

    status = _CALENDAR_HEALTH_STATUS.get(h_source, "FAILED")
    reason = _CALENDAR_HEALTH_REASON.get(h_source)
    severity = _CALENDAR_HEALTH_SEVERITY.get(status, "ERROR")
    recommended_action = _CALENDAR_HEALTH_ACTION.get(status)

    result: dict = {
        "holiday_source": h_source,
        "expiry_source": e_source,
        "status": status,
        "severity": severity,
    }
    if reason:
        result["reason"] = reason
    if recommended_action:
        result["recommended_action"] = recommended_action
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_market_calendar() -> dict:
    """Return the canonical market calendar for today."""
    global _last_expiry_source

    today = date.today()
    holidays, h_source = _load_holidays()
    holiday_name = holidays.get(today)
    is_holiday_today = holiday_name is not None
    is_weekend = today.weekday() >= 5
    is_trading = not is_holiday_today and not is_weekend

    # Expiries — live first, algorithmic fallback per missing index
    live = _live_expiries()
    expiries: dict[str, str] = {}
    days_to_expiry: dict[str, int] = {}
    per_index_expiry_source: dict[str, str] = {}

    for idx in ("nifty", "banknifty", "finnifty", "midcap_nifty", "sensex"):
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

    # Aggregate expiry source: "live" if any index got live data
    agg_expiry_source = "live" if any(v == "live" for v in per_index_expiry_source.values()) else "algorithmic"
    _last_expiry_source = agg_expiry_source

    return {
        "today": {
            "date": today.isoformat(),
            "day": today.strftime("%A"),
            "is_trading_day": is_trading,
            "is_holiday": is_holiday_today,
            "holiday_name": holiday_name,
        },
        "expiries": expiries,
        "days_to_expiry": days_to_expiry,
        "upcoming_holidays": _upcoming_holidays(today),
        "next_trading_day": _next_trading_day(today).isoformat(),
        "week_summary": {
            "trading_days_remaining": _trading_days_remaining_this_week(today),
            "expiry_days_this_week": _expiry_days_this_week(today),
        },
        "source_meta": {
            "holiday_source": h_source,
            "expiry_source": agg_expiry_source,
        },
    }

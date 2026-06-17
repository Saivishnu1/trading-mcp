"""
Economic events calendar — Phase 10.

Static schedule for RBI MPC, US FOMC, India CPI/GDP, and US NFP through 2027.
Supplemented by an optional UPCOMING_EVENTS_JSON env-var for ad-hoc overrides.

SCHEDULE_VALID_UNTIL: set to the last date covered. A WARNING is logged when
today is within 30 days of this boundary so the schedule can be updated in time.

Cache TTL: 3600 s (1 hour) — event list changes slowly.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import date, timedelta

logger = logging.getLogger(__name__)

_TTL = 3600
_CACHE: dict[str, tuple[dict, float]] = {}
_LOCK = threading.Lock()

SCHEDULE_VALID_UNTIL = date(2027, 3, 31)

# Static schedule: (date_str YYYY-MM-DD, event_type, description, impact)
_STATIC: list[tuple[str, str, str, str]] = [
    # ---- RBI MPC 2026 ----
    ("2026-04-09", "RBI_MPC",    "RBI Monetary Policy Committee decision",        "HIGH"),
    ("2026-06-06", "RBI_MPC",    "RBI Monetary Policy Committee decision",        "HIGH"),
    ("2026-08-07", "RBI_MPC",    "RBI Monetary Policy Committee decision",        "HIGH"),
    ("2026-10-09", "RBI_MPC",    "RBI Monetary Policy Committee decision",        "HIGH"),
    ("2026-12-05", "RBI_MPC",    "RBI Monetary Policy Committee decision",        "HIGH"),
    # ---- RBI MPC 2027 ----
    ("2027-02-06", "RBI_MPC",    "RBI Monetary Policy Committee decision",        "HIGH"),
    # ---- US FOMC 2026 ----
    ("2026-06-17", "US_FOMC",    "US Federal Reserve interest rate decision",     "HIGH"),
    ("2026-07-29", "US_FOMC",    "US Federal Reserve interest rate decision",     "HIGH"),
    ("2026-09-16", "US_FOMC",    "US Federal Reserve interest rate decision",     "HIGH"),
    ("2026-10-28", "US_FOMC",    "US Federal Reserve interest rate decision",     "HIGH"),
    ("2026-12-09", "US_FOMC",    "US Federal Reserve interest rate decision",     "HIGH"),
    # ---- US FOMC 2027 ----
    ("2027-01-28", "US_FOMC",    "US Federal Reserve interest rate decision",     "HIGH"),
    ("2027-03-19", "US_FOMC",    "US Federal Reserve interest rate decision",     "HIGH"),
    # ---- India CPI 2026 (approx 12th of each month) ----
    ("2026-07-13", "INDIA_CPI",  "India CPI Inflation release",                  "MEDIUM"),
    ("2026-08-12", "INDIA_CPI",  "India CPI Inflation release",                  "MEDIUM"),
    ("2026-09-14", "INDIA_CPI",  "India CPI Inflation release",                  "MEDIUM"),
    ("2026-10-13", "INDIA_CPI",  "India CPI Inflation release",                  "MEDIUM"),
    ("2026-11-12", "INDIA_CPI",  "India CPI Inflation release",                  "MEDIUM"),
    ("2026-12-14", "INDIA_CPI",  "India CPI Inflation release",                  "MEDIUM"),
    # ---- India CPI 2027 ----
    ("2027-01-13", "INDIA_CPI",  "India CPI Inflation release",                  "MEDIUM"),
    ("2027-02-12", "INDIA_CPI",  "India CPI Inflation release",                  "MEDIUM"),
    ("2027-03-12", "INDIA_CPI",  "India CPI Inflation release",                  "MEDIUM"),
    # ---- India GDP 2026 ----
    ("2026-08-31", "INDIA_GDP",  "India GDP Advance Estimate (Q1 FY27)",         "HIGH"),
    ("2026-11-30", "INDIA_GDP",  "India GDP Second Advance Estimate (Q2 FY27)",  "HIGH"),
    ("2027-02-28", "INDIA_GDP",  "India GDP Advance Estimate (Q3 FY27)",         "HIGH"),
    # ---- US NFP 2026 (first Friday of each month) ----
    ("2026-07-02", "US_NFP",     "US Non-Farm Payrolls",                         "MEDIUM"),
    ("2026-08-07", "US_NFP",     "US Non-Farm Payrolls",                         "MEDIUM"),
    ("2026-09-04", "US_NFP",     "US Non-Farm Payrolls",                         "MEDIUM"),
    ("2026-10-02", "US_NFP",     "US Non-Farm Payrolls",                         "MEDIUM"),
    ("2026-11-06", "US_NFP",     "US Non-Farm Payrolls",                         "MEDIUM"),
    ("2026-12-04", "US_NFP",     "US Non-Farm Payrolls",                         "MEDIUM"),
    # ---- US NFP 2027 ----
    ("2027-01-08", "US_NFP",     "US Non-Farm Payrolls",                         "MEDIUM"),
    ("2027-02-05", "US_NFP",     "US Non-Farm Payrolls",                         "MEDIUM"),
    ("2027-03-05", "US_NFP",     "US Non-Farm Payrolls",                         "MEDIUM"),
]


def _load_static(today: date, cutoff: date) -> list[dict]:
    events = []
    for date_str, etype, desc, impact in _STATIC:
        try:
            d = date.fromisoformat(date_str)
        except ValueError:
            continue
        if today <= d <= cutoff:
            events.append({
                "date":        date_str,
                "event_type":  etype,
                "description": desc,
                "impact":      impact,
                "days_until":  (d - today).days,
            })
    return events


def _load_env_override(today: date, cutoff: date) -> list[dict]:
    raw = os.environ.get("UPCOMING_EVENTS_JSON", "").strip()
    if not raw:
        return []
    try:
        entries = json.loads(raw)
        result = []
        for e in entries:
            d = date.fromisoformat(e["date"])
            if today <= d <= cutoff:
                result.append({
                    "date":        e["date"],
                    "event_type":  e.get("event_type", "CUSTOM"),
                    "description": e.get("description", ""),
                    "impact":      e.get("impact", "MEDIUM"),
                    "days_until":  (d - today).days,
                })
        return result
    except Exception as exc:
        logger.warning("UPCOMING_EVENTS_JSON parse error: %s", exc)
        return []


def nearest_high_impact_days(events: list[dict]) -> int | None:
    """Return days until the nearest HIGH-impact event, or None if none."""
    highs = [e["days_until"] for e in events if e.get("impact") == "HIGH"]
    return min(highs) if highs else None


def get_upcoming_events(days_ahead: int = 7) -> dict:
    """Return economic events scheduled within the next *days_ahead* days."""
    cache_key = f"events_{days_ahead}"
    with _LOCK:
        if cache_key in _CACHE:
            result, ts = _CACHE[cache_key]
            if time.monotonic() - ts < _TTL:
                return result

    today = date.today()

    # Warn when the schedule is about to expire
    days_to_expiry = (SCHEDULE_VALID_UNTIL - today).days
    if days_to_expiry <= 30:
        logger.warning(
            "Event schedule expires in %d days (%s). Update _STATIC in events.py.",
            days_to_expiry, SCHEDULE_VALID_UNTIL,
        )

    cutoff = today + timedelta(days=days_ahead)
    events = _load_static(today, cutoff) + _load_env_override(today, cutoff)
    events.sort(key=lambda e: e["date"])

    result = {
        "days_ahead":    days_ahead,
        "count":         len(events),
        "events":        events,
        "nearest_high_impact_days": nearest_high_impact_days(events),
    }

    with _LOCK:
        _CACHE[cache_key] = (result, time.monotonic())
    return result

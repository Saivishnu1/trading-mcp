"""
Calendar refresh pipeline — Phase 24B (D3, D4).

refresh_calendar(year) orchestrates:
  NSEOfficialProvider → validate → diff → save → reset chain cache

The runtime CalendarProviderChain is NEVER used during refresh.
Only refresh_calendar() contacts the official NSE source.
"""
from __future__ import annotations

from datetime import date

from src.providers.calendar.chain import reset_calendar_provider
from src.providers.calendar.json_provider import JSONCalendarProvider
from src.providers.calendar.nse_provider import NSEOfficialProvider

# ---------------------------------------------------------------------------
# Mandatory holiday keywords — at least one from each group is expected.
# These are loose checks (not hard failures) because holiday names vary by year.
# ---------------------------------------------------------------------------
_MANDATORY_GROUPS: list[tuple[str, ...]] = [
    ("independence", "independence day"),
    ("republic", "republic day"),
    ("gandhi", "gandhi jayanti", "mahatma"),
    ("christmas",),
]

_MIN_HOLIDAYS = 5    # Fewer than this is almost certainly a parse error
_MAX_HOLIDAYS = 30   # More than this is suspicious (NSE has ~12-18 per year)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def refresh_calendar(
    year: int | None = None,
    *,
    dry_run: bool = False,
    nse_provider: NSEOfficialProvider | None = None,
) -> dict:
    """
    Fetch the official NSE holiday list and update the JSON calendar file.

    Args:
        year:         Calendar year to refresh (default: current year).
        dry_run:      Show diffs without writing to disk.
        nse_provider: Override NSEOfficialProvider for testing.

    Returns:
        {
            "updated":          bool,
            "year":             int,
            "previous_version": str | None,
            "new_version":      str | None,
            "changes":          list[dict],
            "validation":       {"status": "passed" | "failed", "errors": list[str]},
            "message":          str,
        }
    """
    if year is None:
        year = date.today().year

    # 1. Fetch from NSE
    provider = nse_provider or NSEOfficialProvider(year=year)
    nse_result = provider.fetch()
    if nse_result is None:
        return {
            "updated": False,
            "year": year,
            "message": "Failed to fetch from NSE official source.",
            "error": "NSEOfficialProvider returned None — check network connectivity.",
            "validation": {"status": "skipped"},
        }

    new_holidays: dict[date, str] = nse_result.data

    # 2. Validate
    valid, errors = validate_holidays(new_holidays, year)
    validation_result = {
        "status": "passed" if valid else "failed",
        "errors": errors,
    }
    if not valid:
        return {
            "updated": False,
            "year": year,
            "message": "Validation failed — existing JSON preserved.",
            "validation": validation_result,
        }

    # 3. Load existing holidays for diff
    json_provider = JSONCalendarProvider()
    existing_meta = json_provider.load(year)
    existing_holidays: dict[date, str] = existing_meta.get("holidays", {})
    prev_version: str | None = existing_meta.get("version")

    # 4. Compute diff
    changes = _compute_changes(existing_holidays, new_holidays)

    if not changes:
        return {
            "updated": False,
            "year": year,
            "current_version": prev_version,
            "changes": [],
            "message": "No changes detected.",
            "validation": validation_result,
        }

    if dry_run:
        return {
            "updated": False,
            "year": year,
            "dry_run": True,
            "previous_version": prev_version,
            "changes": changes,
            "message": f"{len(changes)} change(s) detected (dry run — no files written).",
            "validation": validation_result,
        }

    # 5. Write updated JSON
    new_version = _next_version(prev_version, year)
    json_provider.save(
        year=year,
        holidays=new_holidays,
        version=new_version,
        source="Official NSE Holiday Circular",
        authority="NSE",
    )

    # 6. Invalidate the runtime chain cache so the next request picks up new data
    reset_calendar_provider()

    return {
        "updated": True,
        "year": year,
        "previous_version": prev_version,
        "new_version": new_version,
        "changes": changes,
        "message": f"Calendar updated: {len(changes)} change(s).",
        "validation": validation_result,
    }


# ---------------------------------------------------------------------------
# Validation (D4)
# ---------------------------------------------------------------------------

def validate_holidays(holidays: dict[date, str], year: int) -> tuple[bool, list[str]]:
    """
    Validate a holiday set before writing to disk.

    Checks:
      1. Not empty
      2. Reasonable count (5–30 for a given year)
      3. All dates belong to the target year
      4. No weekday-only-weekend anomaly (all holidays on weekends is suspicious)
      5. No duplicate names within the same year
      6. Advisory warnings for missing well-known holidays (soft check)

    Returns:
        (is_valid, list_of_error_strings)
    """
    errors: list[str] = []

    # 1. Not empty
    if not holidays:
        errors.append("No holidays found — empty set is not valid.")
        return False, errors

    # 2. Reasonable count
    if len(holidays) < _MIN_HOLIDAYS:
        errors.append(
            f"Too few holidays: {len(holidays)} found, expected at least {_MIN_HOLIDAYS}."
        )
    if len(holidays) > _MAX_HOLIDAYS:
        errors.append(
            f"Too many holidays: {len(holidays)} found, expected at most {_MAX_HOLIDAYS}. "
            "Possible parse error."
        )

    # 3. All dates in correct year
    wrong_year = [str(d) for d in holidays if d.year != year]
    if wrong_year:
        errors.append(
            f"Dates from wrong year ({', '.join(wrong_year[:5])}"
            f"{'...' if len(wrong_year) > 5 else ''})."
        )

    # 4. At least some weekday holidays (if ALL fall on weekends, something is wrong)
    weekday_holidays = [d for d in holidays if d.weekday() < 5]
    if not weekday_holidays:
        errors.append(
            "All holidays fall on weekends — likely a data-parsing error. "
            "NSE trading holidays must include at least some weekday holidays."
        )

    # 5. No duplicate names
    name_dates: dict[str, date] = {}
    for d, name in holidays.items():
        if name in name_dates:
            errors.append(
                f"Duplicate holiday name '{name}' appears on {name_dates[name]} and {d}."
            )
        else:
            name_dates[name] = d

    # 6. Advisory: missing well-known holidays (not a hard failure)
    names_lower = [n.lower() for n in holidays.values()]
    missing_groups: list[str] = []
    for group in _MANDATORY_GROUPS:
        if not any(kw in n for kw in group for n in names_lower):
            missing_groups.append(group[0])
    if missing_groups:
        # Soft warning appended to errors list but does NOT cause failure
        errors.append(
            f"Advisory: expected holiday keywords not found: {', '.join(missing_groups)}. "
            "Verify the source data is correct."
        )
        # Don't fail for advisory only — clear errors if this is the only issue
        if len(errors) == 1:
            return True, errors  # Advisory only → valid with warning

    return len(errors) == 0, errors


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _compute_changes(
    old: dict[date, str],
    new: dict[date, str],
) -> list[dict]:
    """Return a list of added/removed/renamed changes between two holiday sets."""
    changes: list[dict] = []

    old_dates = set(old)
    new_dates = set(new)

    for d in sorted(old_dates - new_dates):
        changes.append({"action": "removed", "date": d.isoformat(), "name": old[d]})

    for d in sorted(new_dates - old_dates):
        changes.append({"action": "added", "date": d.isoformat(), "name": new[d]})

    for d in sorted(old_dates & new_dates):
        if old[d] != new[d]:
            changes.append({
                "action":    "renamed",
                "date":      d.isoformat(),
                "old_name":  old[d],
                "new_name":  new[d],
            })

    return changes


def _next_version(prev: str | None, year: int) -> str:
    """Increment the version string within the same year, or start at YYYY.1."""
    if prev is None:
        return f"{year}.1"
    parts = prev.split(".", 1)
    if len(parts) == 2 and parts[0] == str(year):
        try:
            return f"{year}.{int(parts[1]) + 1}"
        except ValueError:
            pass
    return f"{year}.1"

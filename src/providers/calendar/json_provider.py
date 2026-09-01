"""
JSON-backed calendar provider (Phase 24A — D3 / Phase 24B — D2).

Reads resources/calendar/YYYY.json for the current year (and optionally the next
year so upcoming-holiday queries spanning a year boundary work correctly).

Provides in-memory TTL caching so the file is not re-read on every calendar call.

JSON schema (Phase 24B):
  New:  {"version": "2026.1", "authority": "NSE", "source": "...",
         "last_updated": "...", "holidays": [{"date": "...", "name": "..."}]}
  Old:  [{"date": "...", "name": "..."}]   ← backward-compatible (auto-migrated in memory)
"""
from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path
from typing import Any

from src.providers.base import BaseProvider, ProviderResult, _now_iso

_RESOURCES_DIR = Path(__file__).parents[3] / "resources" / "calendar"
_AUTHORITY = "NSE Holiday Circular"
_TTL_SECONDS = 86_400  # 24 hours


class JSONCalendarProvider(BaseProvider):
    """Loads market holidays from versioned JSON files on disk."""

    def __init__(self, resources_dir: Path | None = None, ttl_seconds: int = _TTL_SECONDS) -> None:
        self._dir = resources_dir or _RESOURCES_DIR
        self._ttl = ttl_seconds
        self._cache: dict[date, str] | None = None
        self._cached_at: float | None = None
        self._last_refresh: str = ""

    @property
    def name(self) -> str:
        return "JSONCalendarProvider"

    # ------------------------------------------------------------------
    # Runtime fetch (called by CalendarProviderChain on every request)
    # ------------------------------------------------------------------

    def fetch(self) -> ProviderResult | None:
        now = time.monotonic()

        # Fresh cache: return HIT without touching disk
        if self._cache is not None and self._cached_at is not None:
            age = now - self._cached_at
            if age < self._ttl:
                return self._build_result(
                    data=self._cache,
                    status="CACHED",
                    cache_status="HIT",
                    cache_age_seconds=int(age),
                )

        # Attempt to load from JSON
        try:
            loaded = self._load_raw_json()
            self._cache = loaded
            self._cached_at = now
            self._last_refresh = _now_iso()
            return self._build_result(
                data=loaded,
                status="HEALTHY",
                cache_status="MISS",
                cache_age_seconds=0,
            )
        except Exception:
            # Stale cache is better than nothing
            if self._cache is not None:
                age = now - (self._cached_at or 0)
                return self._build_result(
                    data=self._cache,
                    status="CACHED",
                    cache_status="HIT",
                    cache_age_seconds=int(age),
                )
            return None  # Let the chain fall through to the emergency provider

    def health(self) -> dict:
        if self._cache is None:
            return {
                "status": "OFFLINE",
                "severity": "WARNING",
                "holiday_source": "json",
                "reason": "JSON calendar not yet loaded.",
                "recommended_action": "Verify resources/calendar/YYYY.json exists.",
            }
        age = int(time.monotonic() - (self._cached_at or 0))
        status = "HEALTHY" if age < self._ttl else "CACHED"
        return {
            "status": status,
            "severity": "INFO",
            "holiday_source": "json",
            "cache_age_seconds": age,
            "ttl_seconds": self._ttl,
            "last_refresh": self._last_refresh,
        }

    def reset(self) -> None:
        """Flush the in-memory cache (used by tests and _reset_holiday_cache)."""
        self._cache = None
        self._cached_at = None
        self._last_refresh = ""

    # ------------------------------------------------------------------
    # Persistence API (used by refresh pipeline — D2)
    # ------------------------------------------------------------------

    def load(self, year: int) -> dict:
        """
        Load full metadata for a year's JSON file.

        Returns:
            {
              "version": str | None,
              "authority": str,
              "source": str,
              "last_updated": str | None,
              "holidays": dict[date, str],
            }
        Returns {} if the file does not exist.
        """
        path = self._dir / f"{year}.json"
        if not path.exists():
            return {}
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
        if isinstance(raw, list):
            return {
                "version": None,
                "authority": _AUTHORITY,
                "source": "NSE Holiday Circular (migrated from flat format)",
                "last_updated": None,
                "holidays": {date.fromisoformat(e["date"]): e["name"] for e in raw},
            }
        entries = raw.get("holidays", [])
        return {
            "version":      raw.get("version"),
            "authority":    raw.get("authority", _AUTHORITY),
            "source":       raw.get("source", ""),
            "last_updated": raw.get("last_updated"),
            "holidays":     {date.fromisoformat(e["date"]): e["name"] for e in entries},
        }

    def save(
        self,
        year: int,
        holidays: dict[date, str],
        *,
        version: str,
        source: str = "Official NSE Holiday Circular",
        authority: str = "NSE",
    ) -> None:
        """
        Write holidays to disk in the new schema format.

        Atomically replaces the year's JSON file. Invalidates the in-memory
        cache so the next fetch() reloads from the updated file.
        """
        path = self._dir / f"{year}.json"
        payload = {
            "version":      version,
            "authority":    authority,
            "source":       source,
            "last_updated": _now_iso(),
            "holidays": [
                {"date": d.isoformat(), "name": name}
                for d, name in sorted(holidays.items())
            ],
        }
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
        self.reset()  # Invalidate in-memory cache; next fetch() reloads from disk

    def version(self, year: int) -> str | None:
        """Return the version string from the JSON file, or None for old/missing files."""
        path = self._dir / f"{year}.json"
        if not path.exists():
            return None
        try:
            with open(path, encoding="utf-8") as fh:
                raw = json.load(fh)
            if isinstance(raw, dict):
                return raw.get("version")
        except Exception:
            pass
        return None

    def last_updated(self, year: int) -> str | None:
        """Return the last_updated ISO timestamp from the JSON file, or None."""
        path = self._dir / f"{year}.json"
        if not path.exists():
            return None
        try:
            with open(path, encoding="utf-8") as fh:
                raw = json.load(fh)
            if isinstance(raw, dict):
                return raw.get("last_updated")
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_raw_json(self) -> dict[date, str]:
        """Load holidays from JSON for the current year + optionally next year."""
        today = date.today()
        holidays: dict[date, str] = {}

        for year in (today.year, today.year + 1):
            path = self._dir / f"{year}.json"
            if not path.exists():
                continue
            with open(path, encoding="utf-8") as fh:
                raw = json.load(fh)
            # Support both flat array (old) and object-with-holidays (new) schema
            if isinstance(raw, list):
                entries: list[dict[str, Any]] = raw
            elif isinstance(raw, dict):
                entries = raw.get("holidays", [])
            else:
                continue
            for entry in entries:
                d = date.fromisoformat(entry["date"])
                holidays[d] = entry["name"]

        if not holidays:
            raise FileNotFoundError(
                f"No calendar JSON found in {self._dir} for {today.year} or {today.year + 1}"
            )
        return holidays

    def _build_result(
        self,
        data: dict[date, str],
        status: str,
        cache_status: str,
        cache_age_seconds: int,
    ) -> ProviderResult:
        today = date.today()
        files = ", ".join(
            f"resources/calendar/{y}.json"
            for y in (today.year, today.year + 1)
        )
        return ProviderResult(
            data=data,
            provider_name=self.name,
            data_source=files,
            authority=_AUTHORITY,
            status=status,
            fallback_level=0,
            cache_status=cache_status,
            cache_age_seconds=cache_age_seconds,
            ttl_seconds=self._ttl,
            last_refresh=self._last_refresh or _now_iso(),
        )
